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

#pragma once

#include "lib/string/ob_string.h"
#include "lib/utility/utility.h"
#include <stdio.h>
#include "sql/engine/dml/ob_dml_ctx_define.h"

namespace oceanbase
{
namespace common
{
class ObMySQLProxy;
}
namespace share
{
namespace schema
{
class ObTableSchema;
class ObSchemaGetterGuard;
}
}
}

namespace oceanbase
{
namespace sql
{

class ObTableModifyOp;
class ObDMLStmt;
class ObSQLSessionInfo;

// One AI result column a statement refers to. The table id is the physical
// table id, the column id is the id of the user visible result column.
struct ObAiColumnRef
{
  ObAiColumnRef() : table_id_(OB_INVALID_ID), column_id_(OB_INVALID_ID) {}
  ObAiColumnRef(uint64_t table_id, uint64_t column_id)
    : table_id_(table_id), column_id_(column_id) {}
  int64_t to_string(char *buf, const int64_t buf_len) const
  {
    return snprintf(buf, buf_len, "{table_id: %lu, column_id: %lu}",
                    static_cast<unsigned long>(table_id_),
                    static_cast<unsigned long>(column_id_));
  }
  uint64_t table_id_;
  uint64_t column_id_;
};

// True when the table carries at least one AI column bookkeeping column.
bool table_has_ai_column(const share::schema::ObTableSchema &table_schema);

// Find the canonical name of the AI column the given column belongs to. The
// name stays empty when the column is not an AI column.
int find_ai_column_name(common::ObIAllocator &alloc,
                         const share::schema::ObTableSchema &table_schema,
                         const common::ObString &column_name,
                         common::ObString &ai_column_name);

// Collect every AI result column the statement refers to, including the ones
// used by its sub queries. Only the columns the statement really mentions are
// reported, the strict read check must not touch the other AI columns.
int collect_ai_column_refs(common::ObIAllocator &alloc,
                            share::schema::ObSchemaGetterGuard &schema_guard,
                            ObDMLStmt *stmt,
                            common::ObIArray<ObAiColumnRef> &refs);

// ai_column_strict_read: refuse the statement when one of the AI columns it
// refers to still owns rows that are not READY. The check is column wide, it
// does not only look at the rows the statement selects.
int check_ai_column_strict_read(ObSQLSessionInfo *session,
                                 common::ObMySQLProxy *sql_proxy,
                                 share::schema::ObSchemaGetterGuard &schema_guard,
                                 const common::ObIArray<ObAiColumnRef> &refs);

// Row level maintenance of AI columns.
//
// The three DML operators call into this helper right after a row has been
// handed to DAS. It runs the invalidation UPDATE and the task INSERT through a
// nested SQL session that shares the outer transaction, exactly like the
// foreign key cascade path, so tasks and data commit or roll back together.
class ObAiColumnDml
{
public:
  static int process_insert(ObTableModifyOp &op, const ObInsCtDef &ctdef);
  static int process_update(ObTableModifyOp &op, const ObUpdCtDef &ctdef);
  static int process_delete(ObTableModifyOp &op, const ObDelCtDef &ctdef);

private:
  enum DmlEvent
  {
    AI_DML_INSERT = 0,
    AI_DML_UPDATE = 1,
    AI_DML_DELETE = 2
  };
  static int process(ObTableModifyOp &op,
                     const ObDMLBaseCtDef &ctdef,
                     const DmlEvent event);
};

} // namespace sql
} // namespace oceanbase
