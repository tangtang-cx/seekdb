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

#define USING_LOG_PREFIX SQL_RESV
#include "sql/resolver/ob_resolver.h"
#include "lib/utility/ob_smart_call.h"
#include "lib/stat/ob_diagnostic_info_guard.h"
#include "sql/resolver/cmd/ob_alter_system_resolver.h"
#include "sql/resolver/dml/ob_insert_resolver.h"
#include "sql/resolver/dml/ob_update_resolver.h"
#include "sql/resolver/dml/ob_delete_resolver.h"
#include "sql/resolver/tcl/ob_start_trans_resolver.h"
#include "sql/resolver/tcl/ob_end_trans_resolver.h"
#include "sql/resolver/prepare/ob_prepare_resolver.h"
#include "sql/resolver/prepare/ob_execute_resolver.h"
#include "sql/resolver/prepare/ob_deallocate_resolver.h"
#include "sql/resolver/ddl/ob_create_table_resolver.h"
#include "sql/resolver/ddl/ob_rename_table_resolver.h"
#include "sql/resolver/ddl/ob_truncate_table_resolver.h"
#include "sql/resolver/ddl/ob_fork_table_resolver.h"
#include "sql/resolver/ddl/ob_fork_database_resolver.h"
#include "sql/resolver/ddl/ob_create_table_like_resolver.h"
#include "sql/resolver/ddl/ob_alter_table_resolver.h"
#include "sql/resolver/ddl/ob_drop_table_resolver.h"
#include "sql/resolver/ddl/ob_create_index_resolver.h"
#include "sql/resolver/ddl/ob_drop_index_resolver.h"
#include "sql/resolver/ddl/ob_create_database_resolver.h"
#include "sql/resolver/ddl/ob_alter_database_resolver.h"
#include "sql/resolver/ddl/ob_use_database_resolver.h"
#include "sql/resolver/ddl/ob_drop_database_resolver.h"
#include "sql/resolver/ddl/ob_create_view_resolver.h"
#include "sql/resolver/ddl/ob_explain_resolver.h"
#include "sql/resolver/ddl/ob_create_outline_resolver.h"
#include "sql/resolver/ddl/ob_alter_outline_resolver.h"
#include "sql/resolver/ddl/ob_drop_outline_resolver.h"
#include "sql/resolver/ddl/ob_drop_routine_resolver.h"
#include "sql/resolver/ddl/ob_trigger_resolver.h"
#include "sql/resolver/ddl/ob_optimize_resolver.h"
#include "ddl/ob_drop_routine_resolver.h"
#include "ddl/ob_alter_routine_resolver.h"
#include "sql/resolver/ddl/ob_create_package_resolver.h"
#include "sql/resolver/ddl/ob_drop_package_resolver.h"
#include "sql/resolver/ddl/ob_recyclebin_restore_resolver.h"
#include "sql/resolver/ddl/ob_purge_resolver.h"
#include "sql/resolver/ddl/ob_analyze_stmt_resolver.h"
#include "sql/resolver/ddl/ob_purge_resolver.h"
#include "sql/resolver/ddl/ob_set_comment_resolver.h"
#include "sql/resolver/ddl/ob_lock_table_resolver.h"
#include "sql/resolver/dml/ob_insert_resolver.h"
#include "sql/resolver/dml/ob_update_resolver.h"
#include "sql/resolver/dml/ob_delete_resolver.h"
#include "sql/resolver/dcl/ob_create_user_resolver.h"
#include "sql/resolver/dcl/ob_drop_user_resolver.h"
#include "sql/resolver/dcl/ob_rename_user_resolver.h"
#include "sql/resolver/dcl/ob_set_password_resolver.h"
#include "sql/resolver/dcl/ob_lock_user_resolver.h"
#include "sql/resolver/dcl/ob_grant_resolver.h"
#include "sql/resolver/dcl/ob_revoke_resolver.h"
#include "sql/resolver/dcl/ob_create_role_resolver.h"
#include "sql/resolver/dcl/ob_drop_role_resolver.h"
#include "sql/resolver/dcl/ob_alter_user_role_resolver.h"
#include "sql/resolver/tcl/ob_start_trans_resolver.h"
#include "sql/resolver/tcl/ob_end_trans_resolver.h"
#include "tcl/ob_savepoint_resolver.h"
#include "sql/resolver/cmd/ob_variable_set_resolver.h"
#include "sql/resolver/cmd/ob_show_resolver.h"
#include "sql/resolver/cmd/ob_diff_table_resolver.h"
#include "sql/resolver/cmd/ob_merge_table_resolver.h"
#include "sql/resolver/cmd/ob_kill_resolver.h"
#include "sql/resolver/cmd/ob_set_names_resolver.h"
#include "sql/resolver/cmd/ob_set_transaction_resolver.h"
#include "sql/resolver/cmd/ob_empty_query_resolver.h"
#include "sql/resolver/cmd/ob_anonymous_block_resolver.h"
#include "sql/resolver/cmd/ob_call_procedure_resolver.h"
#include "sql/resolver/cmd/ob_load_data_resolver.h"
#include "sql/resolver/prepare/ob_execute_resolver.h"
#include "sql/resolver/prepare/ob_deallocate_resolver.h"
#include "sql/resolver/ddl/ob_purge_resolver.h"
#include "sql/resolver/ddl/ob_set_comment_resolver.h"
#include "sql/resolver/expr/ob_raw_expr_wrap_enum_set.h"
#include "sql/resolver/cmd/ob_get_diagnostics_resolver.h"
#include "sql/resolver/dcl/ob_alter_role_resolver.h"
#include "sql/pl/ob_pl_package.h"
#include "sql/engine/dml/ob_ai_column_dml.h"
#include "sql/resolver/ddl/ob_ai_column_def.h"
#include "sql/parser/ob_sql_parser.h"
#include "sql/ob_sql_utils.h"
#include "share/schema/ob_schema_getter_guard.h"
#include "share/schema/ob_schema_struct.h"
#include "lib/atomic/ob_atomic.h"
#include "lib/time/ob_time_utility.h"
#include "lib/string/ob_sql_string.h"
#include "lib/utility/ob_print_utils.h"
#include "common/sql_mode/ob_sql_mode.h"

namespace oceanbase
{
using namespace common;
using namespace share;
namespace sql
{

namespace
{

// Collect the actions of an ALTER TABLE statement. The parser chains them with
// T_LINK_NODE, a statement with a single action stores the action as it is.
int collect_alter_actions(ParseNode *node, common::ObSEArray<ParseNode *, 8> &actions)
{
  int ret = OB_SUCCESS;
  if (NULL == node) {
    // no action at all
  } else if (T_LINK_NODE == node->type_) {
    if (OB_FAIL(collect_alter_actions(node->children_[0], actions))) {
    } else if (OB_FAIL(collect_alter_actions(node->children_[1], actions))) {
    }
  } else if (OB_FAIL(actions.push_back(node))) {
  }
  return ret;
}

// Find the RETRY AI COLUMN action of an ALTER TABLE statement. The parser
// merges the actions into one node, every action is a child of it.
ParseNode *find_ai_column_retry_action(const ParseNode &parse_tree, int64_t &action_count)
{
  int ret = OB_SUCCESS;
  ParseNode *retry_node = NULL;
  action_count = 0;
  ParseNode *action_list = parse_tree.children_[1];
  common::ObSEArray<ParseNode *, 8> actions;
  if (NULL != action_list && action_list->num_child_ > 0) {
    for (int64_t i = 0; OB_SUCC(ret) && i < action_list->num_child_; ++i) {
      if (OB_FAIL(collect_alter_actions(action_list->children_[i], actions))) {
      }
    }
  }
  if (OB_SUCC(ret)) {
    action_count = actions.count();
    for (int64_t i = 0; i < actions.count(); ++i) {
      ParseNode *action = actions.at(i);
      if (NULL != action
          && T_ALTER_TABLE_OPTION == action->type_
          && action->num_child_ > 0
          && NULL != action->children_[0]
          && T_AI_COLUMN_RETRY == action->children_[0]->type_) {
        retry_node = action->children_[0];
        break;
      }
    }
  }
  return retry_node;
}

inline bool is_ident_start_char(char c)
{
  return ('a' <= c && c <= 'z') || ('A' <= c && c <= 'Z') || '_' == c || '$' == c;
}

inline bool is_ident_char(char c)
{
  return is_ident_start_char(c) || ('0' <= c && c <= '9');
}

// Copy a quoted literal or a quoted identifier as it is.
int copy_quoted_text(common::ObSqlString &buf,
                      const char *sql,
                      const int64_t len,
                      int64_t &i,
                      const char quote)
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(buf.append_fmt("%c", quote))) {
  } else {
    ++i;
    while (i < len) {
      const char c = sql[i];
      if ('\\' == c && '\'' == quote && i + 1 < len) {
        if (OB_FAIL(buf.append_fmt("%c%c", c, sql[i + 1]))) {
          break;
        }
        i += 2;
      } else if (c == quote) {
        if (i + 1 < len && sql[i + 1] == quote) {
          if (OB_FAIL(buf.append_fmt("%c%c", c, sql[i + 1]))) {
            break;
          }
          i += 2;
        } else {
          if (OB_FAIL(buf.append_fmt("%c", c))) {
            break;
          }
          ++i;
          break;
        }
      } else {
        if (OB_FAIL(buf.append_fmt("%c", c))) {
          break;
        }
        ++i;
      }
    }
  }
  return ret;
}

// Rewrite the STATUS pseudo column of a retry predicate into the state column
// of the AI column. Only the bare identifier is the pseudo column, a backquoted
// one addresses the physical column of the table.
int rewrite_status_pseudo_column(common::ObIAllocator &alloc,
                                  const common::ObString &predicate,
                                  const common::ObString &state_column_name,
                                  common::ObString &rewritten)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  const char *sql = predicate.ptr();
  const int64_t len = predicate.length();
  int64_t i = 0;
  while (i < len && OB_SUCC(ret)) {
    const char c = sql[i];
    if ('\'' == c || '"' == c || '`' == c) {
      ret = copy_quoted_text(buf, sql, len, i, c);
    } else if ('-' == c && i + 1 < len && '-' == sql[i + 1]) {
      // a line comment
      while (i < len && '\n' != sql[i]) {
        if (OB_FAIL(buf.append_fmt("%c", sql[i]))) {
          break;
        }
        ++i;
      }
    } else if ('#' == c) {
      while (i < len && '\n' != sql[i]) {
        if (OB_FAIL(buf.append_fmt("%c", sql[i]))) {
          break;
        }
        ++i;
      }
    } else if ('/' == c && i + 1 < len && '*' == sql[i + 1]) {
      // a block comment
      while (i < len) {
        if ('*' == sql[i] && i + 1 < len && '/' == sql[i + 1]) {
          if (OB_FAIL(buf.append_fmt("*/"))) {
            break;
          }
          i += 2;
          break;
        }
        if (OB_FAIL(buf.append_fmt("%c", sql[i]))) {
          break;
        }
        ++i;
      }
    } else if (is_ident_start_char(c)) {
      int64_t j = i;
      while (j < len && is_ident_char(sql[j])) {
        ++j;
      }
      const common::ObString word(j - i, sql + i);
      int64_t k = j;
      while (k < len && (' ' == sql[k] || '\t' == sql[k])) {
        ++k;
      }
      const bool is_function_call = (k < len && '(' == sql[k]);
      if (!is_function_call
          && 6 == word.length()
          && 0 == STRNCASECMP(word.ptr(), "status", 6)) {
        if (OB_FAIL(buf.append_fmt("`%.*s`",
                                   state_column_name.length(),
                                   state_column_name.ptr()))) {
          break;
        }
      } else if (OB_FAIL(buf.append_fmt("%.*s", word.length(), word.ptr()))) {
        break;
      }
      i = j;
    } else {
      if (OB_FAIL(buf.append_fmt("%c", c))) {
        break;
      }
      ++i;
    }
  }
  if (OB_SUCC(ret)) {
    if (OB_FAIL(common::ob_write_string(alloc, buf.string(), rewritten))) {
    }
  }
  return ret;
}

// The database and the table of the relation factor of an ALTER TABLE.
int extract_relation_names(ObSQLSessionInfo *session_info,
                           ParseNode *relation_node,
                           common::ObString &db_name,
                           common::ObString &table_name)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(relation_node) || relation_node->num_child_ < 2) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    ParseNode *db_node = relation_node->children_[0];
    ParseNode *rel_node = relation_node->children_[1];
    table_name.assign_ptr(const_cast<char *>(rel_node->str_value_), rel_node->str_len_);
    if (NULL == db_node) {
      if (OB_ISNULL(session_info)) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        db_name = session_info->get_database_name();
        if (db_name.empty()) {
          ret = OB_ERR_NO_DB_SELECTED;
        }
      }
    } else {
      db_name.assign_ptr(const_cast<char *>(db_node->str_value_), db_node->str_len_);
    }
  }
  if (OB_SUCC(ret) && !db_name.empty() && !table_name.empty()) {
    ObNameCaseMode mode = OB_NAME_CASE_INVALID;
    ObCollationType cs_type = CS_TYPE_INVALID;
    if (OB_FAIL(session_info->get_name_case_mode(mode))) {
    } else if (OB_FAIL(session_info->get_collation_connection(cs_type))) {
    } else {
      const bool preserve_lettercase = (mode != OB_LOWERCASE_AND_INSENSITIVE);
      ObSQLUtils::check_and_convert_table_name(cs_type, preserve_lettercase, table_name);
      ObSQLUtils::check_and_convert_db_name(cs_type, preserve_lettercase, db_name);
    }
  }
  return ret;
}

// The name of a bookkeeping column of an AI column.
int build_ai_column_name(common::ObIAllocator &alloc,
                          const common::ObString &ai_column_name,
                          const char *suffix,
                          common::ObString &name)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  if (OB_FAIL(buf.append_fmt("%s%.*s%s",
                             AI_COLUMN_HIDDEN_PREFIX,
                             ai_column_name.length(),
                             ai_column_name.ptr(),
                             suffix))) {
  } else if (OB_FAIL(common::ob_write_string(alloc, buf.string(), name))) {
  }
  return ret;
}

// A unique value that marks the update of a retry statement.
void make_retry_marker(char *buf, const int64_t buf_len)
{
  static uint64_t seq = 0;
  const uint64_t id = ATOMIC_AAF(&seq, 1);
  snprintf(buf, static_cast<size_t>(buf_len), "%lx_%lx",
           static_cast<uint64_t>(ObTimeUtility::current_time()), id);
}

} // anonymous namespace

ObResolver::ObResolver(ObResolverParams &params)
    : params_(params)
{

}

ObResolver::~ObResolver()
{
}

template <typename ResolverType>
int ObResolver::stmt_resolver_func(ObResolverParams &params, const ParseNode &parse_tree, ObStmt *&stmt)
{
  int ret = OB_SUCCESS;
  HEAP_VAR(ResolverType, stmt_resolver, params) {
    if (OB_FAIL(SMART_CALL(stmt_resolver.resolve(parse_tree)))) {
    }
    stmt = stmt_resolver.get_basic_stmt();
  }
  return ret;
}

template <typename SelectResolverType>
int ObResolver::select_stmt_resolver_func(ObResolverParams &params, const ParseNode &parse_tree, ObStmt *&stmt)
{
  int ret = OB_SUCCESS;
  HEAP_VAR(SelectResolverType, stmt_resolver, params) {
    stmt_resolver.set_calc_found_rows(true);
    stmt_resolver.set_has_top_limit(true);
    if (OB_FAIL(SMART_CALL(stmt_resolver.resolve(parse_tree)))) {
    }
    stmt = stmt_resolver.get_basic_stmt();
  }
  return ret;
}

int ObResolver::resolve(IsPrepared if_prepared, const ParseNode &parse_tree, ObStmt *&stmt)
{
#define REGISTER_STMT_RESOLVER(name)                                   \
  do {                                                                 \
    ret = stmt_resolver_func<Ob##name##Resolver>(params_, *real_parse_tree, stmt); \
  } while (0)

#define REGISTER_SELECT_STMT_RESOLVER(name)                                   \
  do {                                                                        \
    ret = select_stmt_resolver_func<Ob##name##Resolver>(params_, parse_tree, stmt); \
  } while (0)
  ACTIVE_SESSION_FLAG_SETTER_GUARD(in_resolve);
  int ret = OB_SUCCESS;
  const ParseNode *real_parse_tree = NULL;
  int64_t questionmark_count = 0;
  UNUSED(if_prepared);
  if (OB_ISNULL(params_.allocator_)
      || OB_ISNULL(params_.schema_checker_)
      || OB_ISNULL(params_.session_info_)
      || OB_ISNULL(params_.expr_factory_)
      || OB_ISNULL(params_.query_ctx_)) {
    ret = OB_NOT_INIT;
  } else {
    real_parse_tree = &parse_tree;
  }

  if (OB_SUCC(ret)) {
    params_.resolver_scope_stmt_type_ = parse_tree.type_;
    params_.session_info_->set_stmt_type(
      ObResolverUtils::get_stmt_type_by_item_type(parse_tree.type_));
    ObExecContext *exec_ctx = params_.session_info_->get_cur_exec_ctx();
    if (exec_ctx != nullptr && exec_ctx->get_sql_ctx() != nullptr) {
      //save the current stmt type on my context,
      //some other modules may need to get the current SQL stmt type through its context
      ObSqlCtx *sql_ctx = exec_ctx->get_sql_ctx();
      sql_ctx->stmt_type_ = ObResolverUtils::get_stmt_type_by_item_type(parse_tree.type_);
    }

    switch (real_parse_tree->type_) {
      case T_CREATE_TABLE: {
        REGISTER_STMT_RESOLVER(CreateTable);
        break;
      }
      case T_ALTER_TABLE: {
        int64_t action_count = 0;
        ParseNode *retry_node = find_ai_column_retry_action(parse_tree, action_count);
        if (NULL != retry_node) {
          ret = resolve_ai_column_retry(parse_tree, stmt);
        } else {
          REGISTER_STMT_RESOLVER(AlterTable);
        }
        break;
      }
      case T_CREATE_INDEX: {
        REGISTER_STMT_RESOLVER(CreateIndex);
        break;
      }
      case T_CREATE_VIEW: {
        REGISTER_STMT_RESOLVER(CreateView);
        break;
      }
      case T_ALTER_VIEW: {
#if 0
        ObAlterViewResolver stmt_resolver(params_);
        if (OB_FAIL(stmt_resolver.resolve(*node))) {
        }

        stmt = stmt_resolver.get_basic_stmt();
#endif
        ret = OB_NOT_SUPPORTED;
        LOG_WARN("not support to alter view");
	      LOG_USER_ERROR(OB_NOT_SUPPORTED, "alter view");
        break;
      }
      case T_DROP_VIEW:
      case T_DROP_TABLE: {
        REGISTER_STMT_RESOLVER(DropTable);
        break;
      }
      case T_DROP_INDEX: {
        REGISTER_STMT_RESOLVER(DropIndex);
        break;
      }
      case T_CREATE_TABLE_LIKE: {
        REGISTER_STMT_RESOLVER(CreateTableLike);
        break;
      }
      case T_FORK_TABLE: {
        REGISTER_STMT_RESOLVER(ForkTable);
        break;
      }
      case T_FORK_DATABASE: {
        REGISTER_STMT_RESOLVER(ForkDatabase);
        break;
      }
      case T_DIFF_TABLE: {
        REGISTER_STMT_RESOLVER(DiffTable);
        break;
      }
      case T_MERGE_TABLE: {
        REGISTER_STMT_RESOLVER(MergeTable);
        break;
      }
      case T_SELECT: {
        REGISTER_SELECT_STMT_RESOLVER(Select);
        break;
      }
      case T_INSERT: {
        REGISTER_STMT_RESOLVER(Insert);
        break;
      }
      case T_UPDATE: {
        REGISTER_STMT_RESOLVER(Update);
        break;
      }
      case T_DELETE: {
        REGISTER_STMT_RESOLVER(Delete);
        break;
      }
      case T_BEGIN: {
        REGISTER_STMT_RESOLVER(StartTrans);
        break;
      }
      case T_ROLLBACK:
        //fall through
      case T_COMMIT: {
        REGISTER_STMT_RESOLVER(EndTrans);
        break;
      }
      case T_FREEZE: {
        REGISTER_STMT_RESOLVER(Freeze);
        break;
      }
      case T_FLUSH_CACHE: {
        REGISTER_STMT_RESOLVER(FlushCache);
        break;
      }
      case T_FLUSH_KVCACHE: {
        REGISTER_STMT_RESOLVER(FlushKVCache);
        break;
      }
      case T_FLUSH_ILOGCACHE: {
        REGISTER_STMT_RESOLVER(FlushIlogCache);
        break;
      }
      case T_FLUSH_DAG_WARNINGS: {
        REGISTER_STMT_RESOLVER(FlushDagWarnings);
        break;
      }
      case T_MERGE_CONTROL: {
        REGISTER_STMT_RESOLVER(AdminMerge);
        break;
      }
      case T_CANCEL_TASK: {
        REGISTER_STMT_RESOLVER(CancelTask);
        break;
      }
      case T_REFRESH_MEMORY_STAT: {
        REGISTER_STMT_RESOLVER(RefreshMemStat);
        break;
      }
      case T_REFRESH_IO_CALIBRATION: {
        REGISTER_STMT_RESOLVER(RefreshIOCalibration);
        break;
      }
      case T_SWITCHOVER_TO_STANDBY:
      case T_SWITCHOVER_TO_PRIMARY:
      case T_ACTIVATE_STANDBY: {
        REGISTER_STMT_RESOLVER(SwitchRole);
        break;
      }
      case T_ALTER_SYSTEM_SET_PARAMETER: {
        REGISTER_STMT_RESOLVER(SetConfig);
        break;
      }
      case T_ALTER_SYSTEM_SETTP: {
        REGISTER_STMT_RESOLVER(SetTP);
        break;
      }
      case T_CLEAR_MERGE_ERROR: {
        REGISTER_STMT_RESOLVER(ClearMergeError);
        break;
      }
      case T_CREATE_DATABASE: {
        REGISTER_STMT_RESOLVER(CreateDatabase);
        break;
      }
      case T_USE_DATABASE: {
        REGISTER_STMT_RESOLVER(UseDatabase);
        break;
      }
      case T_ALTER_DATABASE: {
        REGISTER_STMT_RESOLVER(AlterDatabase);
        break;
      }
      case T_DROP_DATABASE: {
        REGISTER_STMT_RESOLVER(DropDatabase);
        break;
      }
      case T_RENAME_TABLE: {
        REGISTER_STMT_RESOLVER(RenameTable);
        break;
      }
      case T_TRUNCATE_TABLE: {
        REGISTER_STMT_RESOLVER(TruncateTable);
        break;
      }
      case T_RECYCLEBIN_RESTORE_TABLE: {
        REGISTER_STMT_RESOLVER(RecyclebinRestoreTable);
        break;
      }
      case T_RECYCLEBIN_RESTORE_DATABASE: {
        REGISTER_STMT_RESOLVER(RecyclebinRestoreDatabase);
        break;
      }
      case T_PURGE_TABLE: {
        REGISTER_STMT_RESOLVER(PurgeTable);
        break;
      }
      case T_PURGE_INDEX: {
        REGISTER_STMT_RESOLVER(PurgeIndex);
        break;
      }
      case T_PURGE_DATABASE: {
        REGISTER_STMT_RESOLVER(PurgeDatabase);
        break;
      }
      case T_PURGE_RECYCLEBIN: {
        REGISTER_STMT_RESOLVER(PurgeRecycleBin);
        break;
      }
      case T_OPTIMIZE_TABLE: {
        REGISTER_STMT_RESOLVER(OptimizeTable);
        break;
      }
      case T_PREPARE: {
        if (params_.is_prepare_protocol_) {
          ret = OB_ERR_PARSE_SQL;
        } else {
          REGISTER_STMT_RESOLVER(Prepare);
        }
        break;
      }
      case T_EXECUTE: {
        if (params_.is_prepare_protocol_) {
          ret = OB_ERR_PARSE_SQL;
        } else {
          REGISTER_STMT_RESOLVER(Execute);
        }
        break;
      }
      case T_DEALLOCATE: {
        if (params_.is_prepare_protocol_) {
          ret = OB_ERR_PARSE_SQL;
        } else {
          REGISTER_STMT_RESOLVER(Deallocate);
        }
        break;
      }
      case T_VARIABLE_SET: {
        REGISTER_STMT_RESOLVER(VariableSet);
        break;
      }
      case T_TRANSACTION: {
        REGISTER_STMT_RESOLVER(SetTransaction);
        break;
      }
      case T_SHOW_TABLES:
      case T_SHOW_DATABASES:
      case T_SHOW_VARIABLES:
      case T_SHOW_COLUMNS:
      case T_SHOW_SCHEMA:
      case T_SHOW_CREATE_DATABASE:
      case T_SHOW_CREATE_TABLE:
      case T_SHOW_CREATE_VIEW:
      case T_SHOW_CREATE_PROCEDURE:
      case T_SHOW_CREATE_FUNCTION:
      case T_SHOW_TABLE_STATUS:
      case T_SHOW_PARAMETERS:
      case T_SHOW_INDEXES:
      case T_SHOW_PROCESSLIST:
      case T_SHOW_WARNINGS:
      case T_SHOW_ERRORS:
      case T_SHOW_TRACE:
      case T_SHOW_ENGINES:
      case T_SHOW_PROFILE:
      case T_SHOW_ENGINE:
      case T_SHOW_OPEN_TABLES:
      case T_SHOW_PRIVILEGES:
      case T_SHOW_CHARSET:
      case T_SHOW_COLLATION:
      case T_SHOW_GRANTS:
      case T_SHOW_RECYCLEBIN:
      case T_SHOW_PROCEDURE_STATUS:
      case T_SHOW_FUNCTION_STATUS:
      case T_SHOW_TRIGGERS:
      case T_SHOW_STATUS:
      case T_SHOW_CREATE_TRIGGER:
      case T_SHOW_CHECK_TABLE:
      case T_SHOW_CREATE_USER: {
        REGISTER_STMT_RESOLVER(Show);
        break;
      }
      case T_CREATE_USER: {
        REGISTER_STMT_RESOLVER(CreateUser);
        break;
      }
      case T_DROP_USER: {
        REGISTER_STMT_RESOLVER(DropUser);
        break;
      }
      case T_RENAME_USER: {
        REGISTER_STMT_RESOLVER(RenameUser);
        break;
      }
      case T_SET_PASSWORD: {
        REGISTER_STMT_RESOLVER(SetPassword);
        break;
      }
      case T_LOCK_USER: {
        REGISTER_STMT_RESOLVER(LockUser);
        break;
      }
      case T_ALTER_USER_DEFAULT_ROLE:
      case T_SET_ROLE: {
        REGISTER_STMT_RESOLVER(AlterUserRole);
        break;
      }

      case T_GRANT_ROLE:
      case T_SYSTEM_GRANT:
      case T_GRANT: {
        REGISTER_STMT_RESOLVER(Grant);
        break;
      }
      case T_SYSTEM_REVOKE:
      case T_REVOKE:
      case T_REVOKE_ALL: {
        REGISTER_STMT_RESOLVER(Revoke);
        break;
      }
      case T_EXPLAIN: {
        REGISTER_STMT_RESOLVER(Explain);
        break;
      }
      case T_ALTER_SYSTEM_SET: {
        REGISTER_STMT_RESOLVER(AlterSystemSet);
        break;
      }
      case T_ALTER_SYSTEM_KILL: {
        REGISTER_STMT_RESOLVER(Kill);
        break;
      }
      case T_ALTER_SESSION_SET: {
        REGISTER_STMT_RESOLVER(AlterSessionSet);
        break;
      }
      case T_SET_NAMES:
        // fall through
      case T_SET_CHARSET: {
        REGISTER_STMT_RESOLVER(SetNames);
        break;
      }
      case T_KILL: {
        REGISTER_STMT_RESOLVER(Kill);
        break;
      }
      case T_EMPTY_QUERY: {
        REGISTER_STMT_RESOLVER(EmptyQuery);
        break;
      }
      case T_FLUSH_PRIVILEGES: {
        REGISTER_STMT_RESOLVER(EmptyQuery);
        break;
      }
      case T_LOCK_TABLE: {
        REGISTER_STMT_RESOLVER(LockTable);
        break;
      }
      case T_CREATE_OUTLINE: {
        REGISTER_STMT_RESOLVER(CreateOutline);
        break;
      }
      case T_ALTER_OUTLINE: {
        REGISTER_STMT_RESOLVER(AlterOutline);
        break;
      }
      case T_DROP_OUTLINE: {
        REGISTER_STMT_RESOLVER(DropOutline);
        break;
      }
      case T_SP_CREATE: {
        REGISTER_STMT_RESOLVER(CreateProcedure);
        break;
      }
      case T_SP_ALTER: {
        REGISTER_STMT_RESOLVER(AlterProcedure);
        break;
      }
      case T_SP_CALL_STMT: {
        REGISTER_STMT_RESOLVER(CallProcedure);
        break;
      }
      case T_SF_CREATE: {
        REGISTER_STMT_RESOLVER(CreateFunction);
        break;
      }
      case T_SF_ALTER: {
        REGISTER_STMT_RESOLVER(AlterFunction);
        break;
      }
      case T_SP_DROP: {
        REGISTER_STMT_RESOLVER(DropProcedure);
        break;
      }
      case T_SF_DROP: {
        REGISTER_STMT_RESOLVER(DropFunction);
        break;
      }
      case T_SP_ANONYMOUS_BLOCK: {
        REGISTER_STMT_RESOLVER(AnonymousBlock);
        break;
      }
      case T_PACKAGE_CREATE: {
        REGISTER_STMT_RESOLVER(CreatePackage);
        break;
      }
      case T_PACKAGE_CREATE_BODY: {
        REGISTER_STMT_RESOLVER(CreatePackageBody);
        break;
      }
      case T_PACKAGE_DROP: {
        REGISTER_STMT_RESOLVER(DropPackage);
        break;
      }
      case T_MYSQL_UPDATE_HISTOGRAM:
      case T_MYSQL_DROP_HISTOGRAM:
      case T_MYSQL_ANALYZE: {
        REGISTER_STMT_RESOLVER(AnalyzeStmt);
        break;
      }
      case T_LOAD_DATA_URL:
      case T_LOAD_DATA: {
        REGISTER_STMT_RESOLVER(LoadData);
        break;
      }
      case T_SET_TABLE_COMMENT:
      case T_SET_COLUMN_COMMENT: {
        REGISTER_STMT_RESOLVER(SetComment);
        break;
      }
      case T_CREATE_ROLE: {
        REGISTER_STMT_RESOLVER(CreateRole);
        break;
      }
      case T_DROP_ROLE: {
        REGISTER_STMT_RESOLVER(DropRole);
        break;
      }
      case T_ALTER_ROLE: {
        REGISTER_STMT_RESOLVER(AlterRole);
        break;
      }
      case T_CREATE_SAVEPOINT:
      case T_ROLLBACK_SAVEPOINT:
      case T_RELEASE_SAVEPOINT: {
        REGISTER_STMT_RESOLVER(SavePoint);
        break;
      }
      case T_TG_CREATE: {
        REGISTER_STMT_RESOLVER(Trigger);
        break;
      }
      case T_TG_DROP: {
        REGISTER_STMT_RESOLVER(Trigger);
        break;
      }
      case T_TG_ALTER: {
        REGISTER_STMT_RESOLVER(Trigger);
        break;
      }
      case T_DIAGNOSTICS: {
        REGISTER_STMT_RESOLVER(GetDiagnostics);
        break;
      }
      case T_ALTER_SYSTEM_RESET_PARAMETER: {
        REGISTER_STMT_RESOLVER(ResetConfig);
        break;
      }
      case T_ALTER_SYSTEM_RESET: {
        REGISTER_STMT_RESOLVER(AlterSystemReset);
        break;
      }
      default: {
        ret = OB_NOT_SUPPORTED;
        const char *type_name = get_type_name(parse_tree.type_);
        LOG_USER_ERROR(OB_NOT_SUPPORTED, "statement type");
        break;
      }
    }  // end switch
    if (OB_SUCC(ret) && stmt->is_dml_write_stmt()) {
      // todo yanli:check leader-follower database
    }
    
    if (OB_SUCC(ret) && stmt->is_dml_stmt() && !params_.session_info_->is_varparams_sql_prepare()) {
      ObDMLStmt *dml_stmt = static_cast<ObDMLStmt*>(stmt);
      ObRawExprWrapEnumSet enum_set_wrapper(*params_.expr_factory_, params_.session_info_);
      if (OB_FAIL(enum_set_wrapper.wrap_enum_set(*dml_stmt))) {
      }
    }

    if (OB_SUCC(ret) && stmt->is_dml_stmt() && !stmt->is_explain_stmt()) {
      if (OB_FAIL(params_.query_ctx_->query_hint_.init_query_hint(params_.allocator_,
                                                                  params_.session_info_,
                                                                  static_cast<ObDMLStmt*>(stmt)))) {
      } else if (OB_FAIL(params_.query_ctx_->query_hint_.check_and_set_params_from_hint(params_,
                                                         *static_cast<ObDMLStmt*>(stmt)))) {
      }
    }

    if (OB_SUCC(ret) && stmt->is_dml_stmt() && !stmt->is_explain_stmt()) {
      bool is_contain_inner_table = false;
      bool is_contain_select_for_update = false;
      ObDMLStmt *dml_stmt = static_cast<ObDMLStmt*>(stmt);
      if (OB_FAIL(dml_stmt->check_if_contain_inner_table(is_contain_inner_table))) {
      } else if (OB_FAIL(dml_stmt->check_if_contain_select_for_update(
                  is_contain_select_for_update))) {
      } else {
        params_.query_ctx_->is_contain_inner_table_ = is_contain_inner_table;
        params_.query_ctx_->is_contain_select_for_update_ = is_contain_select_for_update;
        params_.query_ctx_->has_dml_write_stmt_ = dml_stmt->is_dml_write_stmt();
      }

    }
    if (OB_SUCC(ret)) {
      stmt::StmtType stmt_type = stmt->get_stmt_type();
      if (ObStmt::is_ddl_stmt(stmt_type, stmt->has_global_variable()) || ObStmt::is_dcl_stmt(stmt_type)) {
        ObDDLStmt *ddl_stmt = static_cast<ObDDLStmt*>(stmt);
        obcall::ObDDLArg &ddl_arg = ddl_stmt->get_ddl_arg();

        if (OB_ISNULL(params_.query_ctx_)) {
          ret = OB_ERR_UNEXPECTED;
        } else {
          ddl_arg.ddl_stmt_str_ = params_.query_ctx_->get_sql_stmt();
        }
      }
    }
  }  // end if
  return ret;
}

int ObResolver::resolve_ai_column_retry(const ParseNode &parse_tree, ObStmt *&stmt)
{
  int ret = OB_SUCCESS;
  int64_t action_count = 0;
  ParseNode *retry_node = find_ai_column_retry_action(parse_tree, action_count);
  if (NULL == retry_node) {
    ret = OB_ERR_UNEXPECTED;
    LOG_WARN("the retry action of the alter table is not found", K(ret));
  } else if (action_count != 1) {
    // the retry must be the only action of the statement
    ret = OB_NOT_SUPPORTED;
    LOG_USER_ERROR(OB_NOT_SUPPORTED, "combining AI COLUMN RETRY with another ALTER action");
  } else {
    ret = resolve_ai_column_retry_update(parse_tree, *retry_node, stmt);
  }
  return ret;
}

int ObResolver::resolve_ai_column_retry_update(const ParseNode &parse_tree,
                                               const ParseNode &retry_node,
                                               ObStmt *&stmt)
{
  int ret = OB_SUCCESS;
  ObSQLSessionInfo *session = params_.session_info_;
  ParseNode *column_node = retry_node.children_[0];
  ParseNode *where_node = (retry_node.num_child_ > 1) ? retry_node.children_[1] : NULL;
  common::ObString column_name;
  common::ObString db_name;
  common::ObString table_name;
  common::ObString ai_column_name;
  common::ObString state_name;
  common::ObString request_name;
  common::ObString predicate;
  common::ObSqlString update_sql;
  const share::schema::ObTableSchema *table_schema = NULL;
  const share::schema::ObDatabaseSchema *db_schema = NULL;
  ObSchemaGetterGuard *schema_guard = NULL;
  ObSQLMode sql_mode;

  if (OB_ISNULL(column_node)) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    column_name.assign_ptr(const_cast<char *>(column_node->str_value_), column_node->str_len_);
  }
  // the table the retry applies to
  if (OB_SUCC(ret)
      && OB_FAIL(extract_relation_names(session, parse_tree.children_[0], db_name, table_name))) {
    LOG_WARN("failed to get the table of the retry", K(ret), K(db_name), K(table_name));
  }
  // the column must be an AI column of that table
  if (OB_SUCC(ret)) {
    if (OB_ISNULL(schema_guard = params_.schema_checker_->get_schema_guard())) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(params_.schema_checker_->get_table_schema(db_name,
                                                                  table_name,
                                                                  false/*not index table*/,
                                                                  table_schema))) {
      ObCStringHelper helper;
      LOG_USER_ERROR(OB_TABLE_NOT_EXIST, helper.convert(db_name), helper.convert(table_name));
    } else if (OB_ISNULL(table_schema)) {
      ret = OB_TABLE_NOT_EXIST;
      ObCStringHelper helper;
      LOG_USER_ERROR(OB_TABLE_NOT_EXIST, helper.convert(db_name), helper.convert(table_name));
    } else if (OB_FAIL(find_ai_column_name(*params_.allocator_,
                                           *table_schema,
                                           column_name,
                                           ai_column_name))) {
    } else if (ai_column_name.empty()) {
      ret = OB_NOT_SUPPORTED;
      LOG_USER_ERROR(OB_NOT_SUPPORTED, "retrying a column that is not an AI column");
    }
  }
  // the bookkeeping columns of the AI column
  if (OB_SUCC(ret)) {
    if (OB_FAIL(build_ai_column_name(*params_.allocator_, ai_column_name,
                                     AI_COLUMN_STATE_SUFFIX, state_name))) {
    } else if (OB_FAIL(build_ai_column_name(*params_.allocator_, ai_column_name,
                                             AI_COLUMN_REQUEST_SUFFIX, request_name))) {
    } else if (OB_FAIL(schema_guard->get_database_schema(table_schema->get_database_id(),
                                                          db_schema))) {
      LOG_WARN("failed to get the database schema", K(ret));
    } else if (OB_ISNULL(db_schema)) {
      ret = OB_ERR_UNEXPECTED;
    }
  }
  // the predicate of the retry, the STATUS pseudo column becomes the state
  // column of the AI column
  if (OB_SUCC(ret)
      && NULL != where_node
      && where_node->str_len_ > 0
      && NULL != where_node->str_value_) {
    const common::ObString raw_predicate(where_node->str_len_, where_node->str_value_);
    if (OB_FAIL(rewrite_status_pseudo_column(*params_.allocator_,
                                              raw_predicate,
                                              state_name,
                                              predicate))) {
      LOG_WARN("failed to rewrite the status pseudo column", K(ret));
    }
  }
  // the update that marks the matching rows as pending
  if (OB_SUCC(ret)) {
    char marker[64];
    make_retry_marker(marker, sizeof(marker));
    const common::ObString &real_db_name = db_schema->get_database_name_str();
    const common::ObString &real_table_name = table_schema->get_table_name_str();
    if (OB_FAIL(update_sql.append_fmt("UPDATE `%.*s`.`%.*s` SET `%.*s` = '%s'",
                                       real_db_name.length(), real_db_name.ptr(),
                                       real_table_name.length(), real_table_name.ptr(),
                                       request_name.length(), request_name.ptr(),
                                       marker))) {
    } else if (!predicate.empty()
               && OB_FAIL(update_sql.append_fmt(" WHERE %.*s",
                                                predicate.length(), predicate.ptr()))) {
    }
  }
  // resolve the update, the state column is hidden so the statement has to be
  // resolved with an inner session
  if (OB_SUCC(ret)) {
    ParseResult parse_result;
    MEMSET(&parse_result, 0, SIZEOF(ParseResult));
    parse_result.malloc_pool_ = params_.allocator_;
    {
      sql_mode = session->get_sql_mode();
      ObSQLParser parser(*params_.allocator_, sql_mode);
      if (OB_FAIL(parser.parse(update_sql.ptr(), update_sql.length(), parse_result))) {
        LOG_WARN("failed to parse the retry statement", K(ret), "sql", update_sql.ptr());
      } else if (OB_ISNULL(parse_result.result_tree_)
                 || T_STMT_LIST != parse_result.result_tree_->type_
                 || parse_result.result_tree_->num_child_ < 1
                 || OB_ISNULL(parse_result.result_tree_->children_[0])) {
        ret = OB_ERR_UNEXPECTED;
        LOG_WARN("unexpected parse tree of the retry statement", K(ret));
      } else {
        const ParseNode *update_node = parse_result.result_tree_->children_[0];
        const bool was_inner = session->is_inner();
        const ObSQLSessionInfo::SessionType saved_type = session->get_session_type();
        session->set_inner_session();
        ret = stmt_resolver_func<ObUpdateResolver>(params_, *update_node, stmt);
        if (was_inner) {
          session->set_inner_session();
        } else {
          session->set_user_session();
        }
        session->set_session_type(saved_type);
      }
    }
    parse_terminate(&parse_result);
  }
  return ret;
}

}  // namespace sql
}  // namespace oceanbase
