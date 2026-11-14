/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#define USING_LOG_PREFIX SQL_ENG

#include <new>
#include <stdio.h>
#include <string.h>

#include "sql/engine/dml/ob_ai_column_dml.h"

#include "lib/atomic/ob_atomic.h"
#include "lib/allocator/page_arena.h"
#include "lib/string/ob_sql_string.h"
#include "lib/time/ob_time_utility.h"
#include "lib/utility/utility.h"
#include "common/mysqlclient/ob_mysql_result.h"
#include "common/mysqlclient/ob_mysql_transaction.h"
#include "share/inner_table/ob_inner_table_schema.h"
#include "share/schema/ob_schema_getter_guard.h"
#include "share/schema/ob_table_schema.h"
#include "share/schema/ob_column_schema.h"
#include "sql/engine/dml/ob_table_modify_op.h"
#include "sql/ob_sql_context.h"
#include "share/schema/ob_schema_struct.h"
#include "sql/engine/ob_exec_context.h"
#include "sql/resolver/ddl/ob_ai_column_def.h"
#include "sql/resolver/dml/ob_dml_stmt.h"
#include "sql/resolver/dml/ob_update_stmt.h"
#include "sql/resolver/expr/ob_raw_expr.h"
#include "sql/resolver/expr/ob_raw_expr_util.h"
#include "sql/session/ob_sql_session_info.h"

namespace oceanbase
{
namespace sql
{

using namespace common;
using namespace share::schema;

namespace
{

struct AiRtDef
{
  AiRtDef()
    : def_(),
      dep_ids_(),
      state_name_(),
      request_name_(),
      spec_name_(),
      state_column_id_(OB_INVALID_ID),
      request_column_id_(OB_INVALID_ID),
      spec_column_id_(OB_INVALID_ID),
      result_column_id_(OB_INVALID_ID)
  {}
  ObAiColumnDef def_;
  common::ObSEArray<uint64_t, 4> dep_ids_;
  common::ObString state_name_;
  common::ObString request_name_;
  common::ObString spec_name_;
  // ids of the bookkeeping columns, needed to recognize a retry statement:
  // it assigns the spec column of one AI column and nothing else.
  uint64_t state_column_id_;
  uint64_t request_column_id_;
  uint64_t spec_column_id_;
  uint64_t result_column_id_;
};

// The bookkeeping columns are hidden: the official DDL case asserts that every
// AI column owns exactly three hidden columns. A hidden column cannot be named
// in a WHERE clause of a user session, so the RETRY statement rewrites the
// STATUS pseudo column into the state column and resolves the statement with an
// inner session.
bool is_ai_bookkeeping_column(const ObColumnSchemaV2 *column)
{
  return NULL != column
         && (column->is_hidden() || column->is_invisible_column())
         && is_encoded_ai_column_def(column->get_comment());
}

int build_hidden_name(common::ObIAllocator &alloc,
                      const common::ObString &column_name,
                      const char *suffix,
                      common::ObString &out)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  if (OB_FAIL(buf.append_fmt("__ai_%.*s%s", column_name.length(), column_name.ptr(), suffix))) {
  } else if (OB_FAIL(common::ob_write_string(alloc, buf.string(), out))) {
  }
  return ret;
}

int find_column_id_by_name(const ObTableSchema &table_schema,
                           const common::ObString &column_name,
                           uint64_t &column_id)
{
  int ret = OB_SUCCESS;
  column_id = OB_INVALID_ID;
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (OB_ISNULL(column)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (column->get_column_name_str() == column_name) {
      column_id = column->get_column_id();
      break;
    }
  }
  return ret;
}

int collect_ai_defs(common::ObIAllocator &alloc,
                    const ObTableSchema &table_schema,
                    common::ObIArray<AiRtDef *> &defs)
{
  int ret = OB_SUCCESS;
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (OB_ISNULL(column)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (!is_ai_bookkeeping_column(column)) {
      // not an AI column bookkeeping column
    } else {
      void *rt_def_mem = alloc.alloc(sizeof(AiRtDef));
      AiRtDef *rt_def = (NULL == rt_def_mem) ? NULL : new (rt_def_mem) AiRtDef();
      const ObColumnSchemaV2 *result_column = NULL;
      if (OB_ISNULL(rt_def)) {
        ret = OB_ALLOCATE_MEMORY_FAILED;
      } else if (OB_FAIL(decode_ai_column_def(column->get_comment(), alloc, rt_def->def_))) {
      } else if (OB_ISNULL(result_column = table_schema.get_column_schema(
                             rt_def->def_.column_name_))) {
        ret = OB_ERR_UNEXPECTED;
        LOG_WARN("ai column result column is missing", K(ret), K(rt_def->def_.column_name_));
      } else if (FALSE_IT(rt_def->result_column_id_ = result_column->get_column_id())) {
      } else if (OB_FAIL(build_hidden_name(alloc, rt_def->def_.column_name_,
                                           AI_COLUMN_STATE_SUFFIX, rt_def->state_name_))
                 || OB_FAIL(build_hidden_name(alloc, rt_def->def_.column_name_,
                                              AI_COLUMN_REQUEST_SUFFIX, rt_def->request_name_))
                 || OB_FAIL(build_hidden_name(alloc, rt_def->def_.column_name_,
                                              AI_COLUMN_SPEC_SUFFIX, rt_def->spec_name_))
                 || OB_FAIL(find_column_id_by_name(table_schema, rt_def->state_name_,
                                                   rt_def->state_column_id_))
                 || OB_FAIL(find_column_id_by_name(table_schema, rt_def->request_name_,
                                                   rt_def->request_column_id_))
                 || OB_FAIL(find_column_id_by_name(table_schema, rt_def->spec_name_,
                                                   rt_def->spec_column_id_))) {
      } else {
        // dependency column names -> ids, unknown names (nested function names) are ignored
        const ObString &deps = rt_def->def_.dep_column_names_;
        int32_t start = 0;
        for (int32_t k = 0; OB_SUCC(ret) && k <= deps.length(); ++k) {
          if (k == deps.length() || ',' == deps.ptr()[k]) {
            if (k > start) {
              const ObString name(k - start, deps.ptr() + start);
              const ObColumnSchemaV2 *dep_column = table_schema.get_column_schema(name);
              if (NULL != dep_column
                  && OB_FAIL(rt_def->dep_ids_.push_back(dep_column->get_column_id()))) {
              }
            }
            start = k + 1;
          }
        }
        if (OB_SUCC(ret) && OB_FAIL(defs.push_back(rt_def))) {
        }
      }
    }
  }
  return ret;
}

int find_column_index(const UIntFixedArray &column_ids, const uint64_t column_id, int64_t &index)
{
  int ret = OB_SUCCESS;
  index = -1;
  for (int64_t i = 0; OB_SUCC(ret) && -1 == index && i < column_ids.count(); ++i) {
    if (column_ids.at(i) == column_id) {
      index = i;
    }
  }
  if (-1 == index) {
    ret = OB_ERR_UNEXPECTED;
  }
  return ret;
}

int build_rowkey_predicate(ObTableModifyOp &op,
                           const ObDMLBaseCtDef &ctdef,
                           const ExprFixedArray &row,
                           const ObTableSchema &table_schema,
                           common::ObSqlString &predicate)
{
  int ret = OB_SUCCESS;
  ObEvalCtx &eval_ctx = op.get_eval_ctx();
  common::ObIAllocator &alloc = op.get_exec_ctx().get_allocator();
  const ObObjPrintParams &print_params = op.get_obj_print_params();
  const ObRowkeyInfo &rowkey_info = table_schema.get_rowkey_info();
  for (int64_t i = 0; OB_SUCC(ret) && i < rowkey_info.get_size(); ++i) {
    uint64_t column_id = OB_INVALID_ID;
    int64_t index = -1;
    ObDatum *datum = NULL;
    ObObj obj;
    char *literal = static_cast<char *>(alloc.alloc(256));
    int64_t literal_len = 256;
    int64_t pos = 0;
    const ObColumnSchemaV2 *column = NULL;
    if (OB_FAIL(rowkey_info.get_column_id(i, column_id))) {
    } else if (OB_FAIL(find_column_index(ctdef.column_ids_, column_id, index))) {
      // delete ctdef may only project the rowkey columns, fall back to rowkey order
      index = i;
      ret = OB_SUCCESS;
    } else if (OB_ISNULL(column = table_schema.get_column_schema(column_id))) {
      ret = OB_ERR_UNEXPECTED;
    } else if (index >= row.count()) {
      ret = OB_ERR_UNEXPECTED;
      LOG_WARN("rowkey index is out of range", K(ret), K(index), K(row.count()));
    } else if (OB_FAIL(row.at(index)->eval(eval_ctx, datum))) {
    } else if (OB_ISNULL(datum) || datum->is_null()) {
      ret = OB_ERR_UNEXPECTED;
      LOG_WARN("rowkey value is null", K(ret), K(column_id));
    } else if (OB_FAIL(datum->to_obj(obj, row.at(index)->obj_meta_))) {
    } else if (OB_ISNULL(literal)) {
      ret = OB_ALLOCATE_MEMORY_FAILED;
    } else if (OB_FAIL(obj.print_sql_literal(literal, literal_len, pos, alloc, print_params))) {
    } else if (i > 0 && OB_FAIL(predicate.append(" and "))) {
    } else if (OB_FAIL(predicate.append_fmt("`%.*s` = %.*s",
                                            column->get_column_name_str().length(),
                                            column->get_column_name_str().ptr(),
                                            static_cast<int32_t>(pos), literal))) {
    }
  }
  return ret;
}

int make_request_id(char *buf, const int64_t buf_len)
{
  static uint64_t seq = 0;
  const uint64_t id = ATOMIC_AAF(&seq, 1);
  return snprintf(buf, static_cast<size_t>(buf_len), "%lx_%lx",
                  static_cast<uint64_t>(ObTimeUtility::current_time()), id);
}

// Collect the ids of the user visible result columns of every AI column of the
// table. The bookkeeping columns carry the encoded AI definition, so the
// result column they belong to can be looked up by name.
int collect_ai_result_column_ids(common::ObIAllocator &alloc,
                                 const ObTableSchema &table_schema,
                                 common::ObIArray<uint64_t> &ai_cids)
{
  int ret = OB_SUCCESS;
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (OB_ISNULL(column)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (is_ai_bookkeeping_column(column)) {
      ObAiColumnDef def;
      if (OB_FAIL(decode_ai_column_def(column->get_comment(), alloc, def))) {
      } else {
        const ObColumnSchemaV2 *result_column = table_schema.get_column_schema(def.column_name_);
        if (OB_ISNULL(result_column)) {
          ret = OB_ERR_UNEXPECTED;
          LOG_WARN("ai column result column is missing", K(ret), K(def.column_name_));
        } else if (OB_FAIL(ai_cids.push_back(result_column->get_column_id()))) {
        }
      }
    }
  }
  return ret;
}

// Find the name of the AI column the given result column belongs to.
int find_ai_column_name_by_id(common::ObIAllocator &alloc,
                               const ObTableSchema &table_schema,
                               const uint64_t result_column_id,
                               common::ObString &ai_column_name)
{
  int ret = OB_SUCCESS;
  ai_column_name = common::ObString::make_empty_string();
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (OB_ISNULL(column)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (is_ai_bookkeeping_column(column)) {
      ObAiColumnDef def;
      if (OB_FAIL(decode_ai_column_def(column->get_comment(), alloc, def))) {
      } else {
        const ObColumnSchemaV2 *result_column = table_schema.get_column_schema(def.column_name_);
        if (OB_ISNULL(result_column)) {
          ret = OB_ERR_UNEXPECTED;
          LOG_WARN("ai column result column is missing", K(ret), K(def.column_name_));
        } else if (result_column->get_column_id() == result_column_id) {
          ai_column_name = def.column_name_;
          break;
        }
      }
    }
  }
  return ret;
}

// Count the rows of the table whose AI column is not READY yet.
int count_unfinished_rows(common::ObMySQLProxy *sql_proxy,
                           const char *sql,
                           int64_t &unfinished)
{
  int ret = OB_SUCCESS;
  unfinished = 0;
  ObMySQLTransaction trans;
  ObISQLClient::ReadResult read_result;
  if (OB_FAIL(trans.start(sql_proxy))) {
  } else if (OB_FAIL(trans.read(read_result, sql))) {
  } else if (OB_ISNULL(read_result.get_result())) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    common::sqlclient::ObMySQLResult *result = read_result.get_result();
    int next_ret = result->next();
    if (OB_ITER_END == next_ret) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(next_ret)) {
      ret = next_ret;
    } else if (OB_FAIL(result->get_int("ai_unfinished", unfinished))) {
    }
  }
  return ret;
}

// A column the statement uses. The table name is the name of the table or of
// its alias, the column id is the id of the column in that table.
struct UsedColumn
{
  UsedColumn() : table_name_(), column_id_(OB_INVALID_ID) {}
  common::ObString table_name_;
  uint64_t column_id_;
};

// Collect the columns the given expressions use. The table id of a column
// reference is the query internal one and cannot be used to find the table,
// the name of the table and the id of the column identify the column.
int collect_used_columns(const common::ObIArray<ObRawExpr *> &exprs,
                         common::ObIArray<UsedColumn> &used_cols)
{
  int ret = OB_SUCCESS;
  common::ObSEArray<ObRawExpr *, 16> col_exprs;
  if (OB_FAIL(ObRawExprUtils::extract_column_exprs(exprs, col_exprs))) {
  } else {
    for (int64_t i = 0; OB_SUCC(ret) && i < col_exprs.count(); ++i) {
      const ObRawExpr *expr = col_exprs.at(i);
      if (OB_ISNULL(expr) || T_REF_COLUMN != expr->get_expr_type()) {
        continue;
      }
      const ObColumnRefRawExpr *col_ref = static_cast<const ObColumnRefRawExpr *>(expr);
      UsedColumn used;
      used.table_name_ = col_ref->get_table_name();
      used.column_id_ = col_ref->get_column_id();
      if (OB_INVALID_ID == used.column_id_ || used.table_name_.empty()) {
        continue;
      }
      bool known = false;
      for (int64_t k = 0; !known && k < used_cols.count(); ++k) {
        known = (used_cols.at(k).column_id_ == used.column_id_
                 && ObCharset::case_insensitive_equal(used_cols.at(k).table_name_,
                                                     used.table_name_));
      }
      if (!known && OB_FAIL(used_cols.push_back(used))) {
      }
    }
  }
  return ret;
}

// Remember a reference to an AI column. The different sources may report the
// same column, the list has to stay free of duplicates.
int add_ai_column_ref(common::ObIArray<ObAiColumnRef> &refs,
                       const uint64_t table_id,
                       const uint64_t column_id)
{
  int ret = OB_SUCCESS;
  bool known = false;
  for (int64_t i = 0; !known && i < refs.count(); ++i) {
    known = (refs.at(i).table_id_ == table_id && refs.at(i).column_id_ == column_id);
  }
  if (!known && OB_FAIL(refs.push_back(ObAiColumnRef(table_id, column_id)))) {
  }
  return ret;
}

} // anonymous namespace

bool table_has_ai_column(const share::schema::ObTableSchema &table_schema)
{
  bool found = false;
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; !found && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (is_ai_bookkeeping_column(column)) {
      found = true;
    }
  }
  return found;
}

int find_ai_column_name(common::ObIAllocator &alloc,
                         const share::schema::ObTableSchema &table_schema,
                         const common::ObString &column_name,
                         common::ObString &ai_column_name)
{
  int ret = OB_SUCCESS;
  ai_column_name = common::ObString::make_empty_string();
  const int64_t column_count = table_schema.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < column_count; ++i) {
    const ObColumnSchemaV2 *column = table_schema.get_column_schema_by_idx(i);
    if (OB_ISNULL(column)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (is_ai_bookkeeping_column(column)) {
      ObAiColumnDef def;
      if (OB_FAIL(decode_ai_column_def(column->get_comment(), alloc, def))) {
      } else if (ObCharset::case_insensitive_equal(def.column_name_, column_name)) {
        ai_column_name = def.column_name_;
        break;
      }
    }
  }
  return ret;
}

int collect_ai_column_refs(common::ObIAllocator &alloc,
                            share::schema::ObSchemaGetterGuard &schema_guard,
                            ObDMLStmt *stmt,
                            common::ObIArray<ObAiColumnRef> &refs)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(stmt)) {
    ret = OB_INVALID_ARGUMENT;
  } else {
    // (a) the resolved column items know the physical table id of every
    //     column they refer to, they cover the select list, the assignment
    //     columns and the columns of the predicate of a select statement
    const common::ObIArray<ColumnItem> &column_items = stmt->get_column_items();
    uint64_t cached_table_id = OB_INVALID_ID;
    common::ObSEArray<uint64_t, 4> ai_cids;
    for (int64_t i = 0; OB_SUCC(ret) && i < column_items.count(); ++i) {
      const ColumnItem &item = column_items.at(i);
      if (OB_INVALID_ID == item.base_tid_ || OB_INVALID_ID == item.column_id_) {
        // not a base table column
        continue;
      }
      if (item.base_tid_ != cached_table_id) {
        const ObTableSchema *table_schema = NULL;
        ai_cids.reset();
        cached_table_id = OB_INVALID_ID;
        if (OB_FAIL(schema_guard.get_table_schema(item.base_tid_, table_schema))) {
          LOG_WARN("failed to get table schema", K(ret), "table_id", item.base_tid_);
        } else if (OB_ISNULL(table_schema)) {
          // not a base table, the column cannot be an AI column
        } else if (OB_FAIL(collect_ai_result_column_ids(alloc, *table_schema, ai_cids))) {
        } else {
          cached_table_id = item.base_tid_;
        }
      }
      if (OB_SUCC(ret) && cached_table_id == item.base_tid_) {
        for (int64_t k = 0; OB_SUCC(ret) && k < ai_cids.count(); ++k) {
          if (ai_cids.at(k) == item.column_id_) {
            if (OB_FAIL(add_ai_column_ref(refs, item.base_tid_, item.column_id_))) {
            }
            break;
          }
        }
      }
    }
    // (b) the predicate of an update or a delete does not show up in the
    //     column items of the statement, the columns it uses are collected
    //     from the condition expressions and matched against the AI columns
    //     of the base tables of the statement
    common::ObSEArray<UsedColumn, 16> used_cols;
    if (OB_SUCC(ret) && OB_FAIL(collect_used_columns(stmt->get_condition_exprs(), used_cols))) {
    } else if (OB_SUCC(ret) && used_cols.count() > 0) {
      // the assignment columns of an update are not part of the column items
      // of the statement either
      if (stmt->is_update_stmt()) {
        const ObUpdateStmt *update_stmt = static_cast<const ObUpdateStmt *>(stmt);
        const common::ObIArray<ObUpdateTableInfo *> &table_info = update_stmt->get_update_table_info();
        for (int64_t i = 0; OB_SUCC(ret) && i < table_info.count(); ++i) {
          const ObUpdateTableInfo *info = table_info.at(i);
          if (OB_ISNULL(info)) {
            continue;
          }
          for (int64_t j = 0; OB_SUCC(ret) && j < info->assignments_.count(); ++j) {
            const ObColumnRefRawExpr *column_expr = info->assignments_.at(j).column_expr_;
            if (OB_ISNULL(column_expr) || OB_INVALID_ID == column_expr->get_column_id()) {
              continue;
            }
            UsedColumn used;
            used.table_name_ = column_expr->get_table_name();
            used.column_id_ = column_expr->get_column_id();
            if (used.table_name_.empty()) {
              continue;
            }
            bool known = false;
            for (int64_t k = 0; !known && k < used_cols.count(); ++k) {
              known = (used_cols.at(k).column_id_ == used.column_id_
                       && ObCharset::case_insensitive_equal(used_cols.at(k).table_name_,
                                                           used.table_name_));
            }
            if (!known && OB_FAIL(used_cols.push_back(used))) {
            }
          }
        }
      }
      const common::ObIArray<TableItem *> &table_items = stmt->get_table_items();
      for (int64_t t = 0; OB_SUCC(ret) && t < table_items.count(); ++t) {
        const TableItem *table_item = table_items.at(t);
        if (OB_ISNULL(table_item) || !table_item->is_basic_table()) {
          continue;
        }
        // the ref id of a base table is the physical table id
        const uint64_t table_id = table_item->ref_id_;
        if (OB_INVALID_ID == table_id) {
          continue;
        }
        const common::ObString &table_name = table_item->get_table_name();
        const ObTableSchema *table_schema = NULL;
        common::ObSEArray<uint64_t, 4> table_ai_cids;
        if (OB_FAIL(schema_guard.get_table_schema(table_id, table_schema))) {
          LOG_WARN("failed to get table schema", K(ret), "table_id", table_id);
        } else if (OB_ISNULL(table_schema)) {
          // not a base table, the column cannot be an AI column
        } else if (OB_FAIL(collect_ai_result_column_ids(alloc, *table_schema, table_ai_cids))) {
        } else {
          for (int64_t c = 0; OB_SUCC(ret) && c < used_cols.count(); ++c) {
            if (!ObCharset::case_insensitive_equal(used_cols.at(c).table_name_, table_name)) {
              // the column belongs to another table
              continue;
            }
            for (int64_t k = 0; OB_SUCC(ret) && k < table_ai_cids.count(); ++k) {
              if (table_ai_cids.at(k) == used_cols.at(c).column_id_) {
                if (OB_FAIL(add_ai_column_ref(refs, table_id, table_ai_cids.at(k)))) {
                }
                break;
              }
            }
          }
        }
      }
    }
    // (c) the sub queries of the statement
    if (OB_SUCC(ret)) {
      common::ObSEArray<ObSelectStmt *, 4> child_stmts;
      if (OB_FAIL(stmt->get_child_stmts(child_stmts))) {
      } else {
        for (int64_t i = 0; OB_SUCC(ret) && i < child_stmts.count(); ++i) {
          if (OB_FAIL(collect_ai_column_refs(alloc, schema_guard, child_stmts.at(i), refs))) {
          }
        }
      }
    }
  }
  return ret;
}

int check_ai_column_strict_read(ObSQLSessionInfo *session,
                                 common::ObMySQLProxy *sql_proxy,
                                 share::schema::ObSchemaGetterGuard &schema_guard,
                                 const common::ObIArray<ObAiColumnRef> &refs)
{
  int ret = OB_SUCCESS;
  bool strict_read = false;
  if (OB_ISNULL(session) || OB_ISNULL(sql_proxy) || 0 == refs.count()) {
    return OB_SUCCESS;
  }
  if (session->is_in_ai_column_maintenance()) {
    // the nested statements of the AI helper must never be blocked
    return OB_SUCCESS;
  }
  if (OB_FAIL(session->get_sys_variable(share::SYS_VAR_AI_COLUMN_STRICT_READ, strict_read))) {
    // do not block the statement when the variable cannot be read
    LOG_WARN("failed to read ai_column_strict_read", K(ret));
    strict_read = false;
  }
  if (!strict_read) {
    return OB_SUCCESS;
  }
  common::ObArenaAllocator alloc;
  for (int64_t i = 0; OB_SUCC(ret) && i < refs.count(); ++i) {
    const ObAiColumnRef &ref = refs.at(i);
    const ObTableSchema *table_schema = NULL;
    const ObDatabaseSchema *db_schema = NULL;
    common::ObString ai_column_name;
    common::ObString state_name;
    int64_t unfinished = 0;
    if (OB_FAIL(schema_guard.get_table_schema(ref.table_id_, table_schema))) {
      LOG_WARN("failed to get table schema", K(ret), "table_id", ref.table_id_);
    } else if (OB_ISNULL(table_schema)) {
      // the table is gone, nothing to check
    } else if (OB_FAIL(schema_guard.get_database_schema(table_schema->get_database_id(), db_schema))) {
      LOG_WARN("failed to get database schema", K(ret));
    } else if (OB_ISNULL(db_schema)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(find_ai_column_name_by_id(alloc, *table_schema, ref.column_id_, ai_column_name))) {
    } else if (ai_column_name.empty()) {
      // not an AI column any more
    } else if (OB_FAIL(build_hidden_name(alloc, ai_column_name, AI_COLUMN_STATE_SUFFIX, state_name))) {
    } else {
      const common::ObString &db_name = db_schema->get_database_name_str();
      const common::ObString &table_name = table_schema->get_table_name_str();
      common::ObSqlString sql;
      if (OB_FAIL(sql.append_fmt("SELECT COUNT(*) AS ai_unfinished FROM `%.*s`.`%.*s` "
                                 "WHERE `%.*s` IS NULL OR `%.*s` <> 'READY'",
                                 db_name.length(), db_name.ptr(),
                                 table_name.length(), table_name.ptr(),
                                 state_name.length(), state_name.ptr(),
                                 state_name.length(), state_name.ptr()))) {
      } else if (OB_FAIL(count_unfinished_rows(sql_proxy, sql.ptr(), unfinished))) {
        // do not block the statement when the state cannot be read
        LOG_WARN("failed to count the unfinished ai column rows", K(ret), "sql", sql.ptr());
      } else if (unfinished > 0) {
        ret = OB_AI_COLUMN_UNFINISHED_TASKS;
        LOG_USER_ERROR(OB_AI_COLUMN_UNFINISHED_TASKS, ref.table_id_, ref.column_id_);
      }
    }
  }
  return ret;
}

int ObAiColumnDml::process_insert(ObTableModifyOp &op, const ObInsCtDef &ctdef)
{
  return process(op, ctdef, AI_DML_INSERT);
}

int ObAiColumnDml::process_update(ObTableModifyOp &op, const ObUpdCtDef &ctdef)
{
  return process(op, ctdef, AI_DML_UPDATE);
}

int ObAiColumnDml::process_delete(ObTableModifyOp &op, const ObDelCtDef &ctdef)
{
  return process(op, ctdef, AI_DML_DELETE);
}

int ObAiColumnDml::process(ObTableModifyOp &op,
                           const ObDMLBaseCtDef &ctdef,
                           const DmlEvent event)
{
  int ret = OB_SUCCESS;
  ObExecContext &ctx = op.get_exec_ctx();
  ObSQLSessionInfo *session = ctx.get_my_session();
  ObSqlCtx *sql_ctx = ctx.get_sql_ctx();
  ObSchemaGetterGuard *schema_guard = NULL;
  const ObTableSchema *table_schema = NULL;
  const ObDatabaseSchema *db_schema = NULL;
  common::ObIAllocator &alloc = ctx.get_allocator();
  common::ObSEArray<AiRtDef *, 4> defs;
  // NOTE: das_base_ctdef_.table_id_ is the query-internal table-loc id, NOT the
  // physical table id (see ObTableModifyOp::has_ai_column). index_tid_ is the
  // physical id; try it first and fall back to table_id_.
  const uint64_t cand_ids[2] = { ctdef.das_base_ctdef_.index_tid_,
                                 ctdef.das_base_ctdef_.table_id_ };
  bool need_maintenance = true;
  // index of the AI column that a retry statement asks to derive again, -1 when
  // this is an ordinary DML statement.
  int64_t retry_def_idx = -1;

  if (OB_ISNULL(session) || OB_ISNULL(sql_ctx)
      || OB_ISNULL(schema_guard = sql_ctx->schema_guard_)) {
    ret = OB_ERR_UNEXPECTED;
  } else if (session->is_in_ai_column_maintenance()) {
    // nested maintenance statement issued by this helper, do not recurse.
    // NOTE: table_schema stays NULL in this branch; mark skip so the code
    // below never dereferences it.
    need_maintenance = false;
  } else {
    for (int64_t i = 0; OB_SUCC(ret) && i < 2; ++i) {
      table_schema = NULL;
      if (OB_FAIL(schema_guard->get_table_schema(cand_ids[i], table_schema))) {
        LOG_WARN("failed to get table schema", K(ret), "table_id", cand_ids[i]);
      } else if (NULL != table_schema) {
        break;
      } else if (1 == i) {
        ret = OB_ERR_UNEXPECTED;
      }
    }
  }
  const uint64_t table_id = (NULL != table_schema) ? table_schema->get_table_id()
                                                   : OB_INVALID_ID;
  if (OB_FAIL(ret) || !need_maintenance) {
    // pass through, or nested maintenance: skip all schema work
  } else if (OB_FAIL(collect_ai_defs(alloc, *table_schema, defs))) {
  } else if (OB_FAIL(schema_guard->get_database_schema(table_schema->get_database_id(),
                                                       db_schema))) {
    LOG_WARN("failed to get database schema", K(ret), K(table_schema->get_database_id()));
  } else if (OB_ISNULL(db_schema)) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    LOG_INFO("[AI_PROBE] collect", "table_id", table_schema->get_table_id(),
             "def_cnt", defs.count(), "col_cnt", table_schema->get_column_count());
  }

  if (OB_FAIL(ret) || !need_maintenance) {
    // pass through, or nested maintenance: nothing to compare
  } else if (AI_DML_UPDATE == event) {
    const ObUpdCtDef &upd_ctdef = static_cast<const ObUpdCtDef &>(ctdef);
    need_maintenance = false;
    // A retry statement assigns the request column of exactly one AI column and
    // touches nothing else: it puts the matching rows of that AI column back
    // into the pending state, the other AI columns of the row keep their value.
    for (int64_t i = 0; OB_SUCC(ret) && retry_def_idx < 0 && i < upd_ctdef.assign_columns_.count(); ++i) {
      const ColumnContent &content = upd_ctdef.assign_columns_.at(i);
      if (content.projector_index_ < 0 || content.projector_index_ >= ctdef.column_ids_.count()) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        const uint64_t column_id = ctdef.column_ids_.at(content.projector_index_);
        for (int64_t k = 0; OB_SUCC(ret) && k < defs.count(); ++k) {
          if (defs.at(k)->request_column_id_ == column_id) {
            retry_def_idx = k;
            need_maintenance = true;
            break;
          }
        }
      }
    }
    if (!need_maintenance
        && (ctdef.old_row_.count() == 0 || ctdef.old_row_.count() != ctdef.new_row_.count())) {
      need_maintenance = true;
    }
    // primary key change always regenerates the result
    const ObRowkeyInfo &rowkey_info = table_schema->get_rowkey_info();
    for (int64_t i = 0; OB_SUCC(ret) && !need_maintenance && i < rowkey_info.get_size(); ++i) {
      uint64_t column_id = OB_INVALID_ID;
      int64_t index = -1;
      ObDatum *old_datum = NULL;
      ObDatum *new_datum = NULL;
      if (OB_FAIL(rowkey_info.get_column_id(i, column_id))) {
      } else if (OB_FAIL(find_column_index(ctdef.column_ids_, column_id, index))) {
      } else if (OB_FAIL(ctdef.old_row_.at(index)->eval(op.get_eval_ctx(), old_datum))
                 || OB_FAIL(ctdef.new_row_.at(index)->eval(op.get_eval_ctx(), new_datum))) {
      } else if (OB_ISNULL(old_datum) || OB_ISNULL(new_datum)) {
        ret = OB_ERR_UNEXPECTED;
      } else if (!ObDatum::binary_equal(*old_datum, *new_datum)) {
        need_maintenance = true;
      }
    }
    // dependency column change
    for (int64_t i = 0; OB_SUCC(ret) && !need_maintenance
                        && i < upd_ctdef.assign_columns_.count(); ++i) {
      const ColumnContent &content = upd_ctdef.assign_columns_.at(i);
      const uint64_t column_id = ctdef.column_ids_.at(content.projector_index_);
      for (int64_t k = 0; !need_maintenance && k < defs.count(); ++k) {
        for (int64_t d = 0; !need_maintenance && d < defs.at(k)->dep_ids_.count(); ++d) {
          if (defs.at(k)->dep_ids_.at(d) == column_id) {
            need_maintenance = true;
          }
        }
      }
    }
  }

  if (OB_FAIL(ret) || !need_maintenance) {
    // nothing to do
  } else {
    common::ObSqlString predicate;
    common::ObSqlString update_sql;
    common::ObSqlString task_sql;
    char request_id[64];
    LOG_INFO("[AI_PROBE] building task sql", "table_id", table_id, "event", (int)event);
    make_request_id(request_id, sizeof(request_id));
    const int32_t request_id_len = static_cast<int32_t>(strlen(request_id));
    const common::ObString db_name = db_schema->get_database_name_str();
    const common::ObString &table_name = table_schema->get_table_name_str();
    const ExprFixedArray &rowkey_row = (AI_DML_DELETE == event) ? ctdef.old_row_ : ctdef.new_row_;
    if (OB_FAIL(build_rowkey_predicate(op, ctdef, rowkey_row, *table_schema, predicate))) {
    } else if (AI_DML_DELETE == event) {
      if (OB_FAIL(task_sql.append_fmt("delete from oceanbase.%s where table_id = %lu and rowkey_predicate = ",
                                      OB_ALL_AI_COLUMN_TASK_TNAME, table_id))) {
      } else if (OB_FAIL(sql_append_hex_escape_str(predicate.string(), task_sql))) {
      }
    } else {
      // 1) invalidate the result columns and record the new request id
      if (OB_FAIL(update_sql.append_fmt("update `%.*s`.`%.*s` set ",
                                        db_name.length(), db_name.ptr(),
                                        table_name.length(), table_name.ptr()))) {
      }
      for (int64_t i = 0; OB_SUCC(ret) && i < defs.count(); ++i) {
        if (retry_def_idx >= 0 && i != retry_def_idx) {
          // a retry only touches the AI column it names
          continue;
        }
        const AiRtDef &rt_def = *defs.at(i);
        if ((AI_DML_UPDATE == event || retry_def_idx >= 0)
            && OB_FAIL(update_sql.append_fmt("`%.*s` = NULL, ",
                                             rt_def.def_.column_name_.length(),
                                             rt_def.def_.column_name_.ptr()))) {
        } else if (OB_FAIL(update_sql.append_fmt(
                     "`%.*s` = 'PENDING', `%.*s` = '%.*s', `%.*s` = '%lu', ",
                     rt_def.state_name_.length(), rt_def.state_name_.ptr(),
                     rt_def.request_name_.length(), rt_def.request_name_.ptr(),
                     request_id_len, request_id,
                     rt_def.spec_name_.length(), rt_def.spec_name_.ptr(),
                     rt_def.def_.definition_version_))) {
        }
      }
      if (OB_SUCC(ret)) {
        // drop the trailing ", "
        if (OB_FAIL(update_sql.set_length(update_sql.length() - 2))) {
          LOG_WARN("failed to trim sql", K(ret));
        }
        if (OB_FAIL(update_sql.append_fmt(" where %.*s",
                                          predicate.string().length(),
                                          predicate.string().ptr()))) {
        }
      }
      // 2) publish the tasks
      if (OB_SUCC(ret)
          && OB_FAIL(task_sql.append_fmt(
               "insert into oceanbase.%s (table_id, column_id, request_id, rowkey_predicate, "
               "eligible_ts, state, retry_count) values ",
               OB_ALL_AI_COLUMN_TASK_TNAME))) {
      }
      int64_t task_value_cnt = 0;
      for (int64_t i = 0; OB_SUCC(ret) && i < defs.count(); ++i) {
        if (retry_def_idx >= 0 && i != retry_def_idx) {
          // a retry only creates tasks for the AI column it names
          continue;
        }
        const share::schema::ObColumnSchemaV2 *col_schema =
            table_schema->get_column_schema(defs.at(i)->def_.column_name_);
        uint64_t column_id = OB_INVALID_ID;
        if (OB_ISNULL(col_schema)) {
          ret = OB_ERR_UNEXPECTED;
          LOG_WARN("[AI_PROBE] ai column schema not found", K(ret),
                   "column", defs.at(i)->def_.column_name_, K(table_id));
        } else if (OB_FAIL(task_sql.append_fmt("%s(%lu, %lu, ", 0 == task_value_cnt ? "" : ", ",
                                        table_id, col_schema->get_column_id()))) {
        } else if (OB_FAIL(sql_append_hex_escape_str(ObString(request_id_len, request_id),
                                                     task_sql))) {
        } else if (OB_FAIL(task_sql.append(", "))) {
        } else if (OB_FAIL(sql_append_hex_escape_str(predicate.string(), task_sql))) {
        } else if (OB_FAIL(task_sql.append(", now(6), 1, 0)"))) {
        } else {
          ++task_value_cnt;
        }
      }
    }
    if (OB_SUCC(ret)) {
      session->set_in_ai_column_maintenance(true);
      // mark nested sql triggered by ai column maintenance, same as fk cascading,
      // so that the inner statement skips start/end stmt bookkeeping.
      op.get_exec_ctx().get_das_ctx().is_ai_column_cascading_ = true;
      LOG_INFO("[AI_PROBE] executing task sql", K(table_id));
      if (OB_FAIL(op.open_inner_conn())) {
        LOG_INFO("[AI_PROBE] open inner conn failed", K(ret));
      } else if (OB_FAIL(op.begin_nested_session(true))) {
        LOG_INFO("[AI_PROBE] begin nested session failed", K(ret));
      } else {
        if (AI_DML_DELETE != event && OB_FAIL(op.execute_write(update_sql.ptr()))) {
          LOG_INFO("[AI_PROBE] invalidate sql failed", K(ret), "sql", update_sql.ptr());
        } else if (OB_FAIL(op.execute_write(task_sql.ptr()))) {
          LOG_INFO("[AI_PROBE] task sql failed", K(ret), "sql", task_sql.ptr());
        }
        int end_ret = op.end_nested_session();
        if (OB_SUCCESS != end_ret) {
          LOG_INFO("[AI_PROBE] end nested session failed", K(end_ret));
          if (OB_SUCC(ret)) {
            ret = end_ret;
          }
        }
      }
      op.get_exec_ctx().get_das_ctx().is_ai_column_cascading_ = false;
      session->set_in_ai_column_maintenance(false);
    }
  }
  LOG_INFO("[AI_PROBE] process end", K(ret), "event", (int)event, K(table_id));
  return ret;
}

} // namespace sql
} // namespace oceanbase
