"""baseline — schema hiện tại (đã tạo qua Base.metadata.create_all + hand-rolled
migration cũ trong app/database.py: _migrate_sqlite_columns / _migrate_postgres_columns)

Migration này KHÔNG làm gì — nó chỉ đánh dấu điểm bắt đầu để Alembic quản lý các
thay đổi schema TỪ ĐÂY VỀ SAU. Trên database đang chạy (đã có đủ bảng/cột), chạy:

    alembic stamp head

KHÔNG chạy `alembic upgrade head` trên DB đã có sẵn dữ liệu — vì baseline không tạo
bảng, upgrade sẽ không gây hại, nhưng stamp là cách đúng để nói với Alembic "coi như
đã chạy xong revision này rồi, đừng làm lại".

Trên DB hoàn toàn mới (CI, máy dev mới): app vẫn tự tạo bảng qua init_db() lúc
khởi động (create_all + hand-rolled migration) như trước — Alembic baseline không
thay thế bước đó, chỉ tiếp quản các thay đổi SAU thời điểm này.

Revision ID: 834e9b769af0
Revises:
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "834e9b769af0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
