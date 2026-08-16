"""
BI Semantics Configuration Model - per-user default measure/aggregation
mapping per business table (e.g. sales orders default to SUM(net_value)
rather than row count). See app/services/bi_semantics_service.py for the
built-in defaults this table is layered on top of, and
app/services/databridge_services/agents/sql_generator_agent.py for where
it's consulted when a question is ambiguous about what to measure.
"""
from app import db
from datetime import datetime


class BiSemanticsConfig(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'bi_semantics_configs'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'table_name', name='uq_bi_semantics_user_table'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)

    table_name = db.Column(db.String(200), nullable=False)
    entity_label = db.Column(db.String(200), nullable=True)
    measure_column = db.Column(db.String(200), nullable=False)
    aggregation = db.Column(db.String(20), nullable=False, default='SUM')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "company_code": self.company_code,
            "table_name": self.table_name,
            "entity_label": self.entity_label,
            "measure_column": self.measure_column,
            "aggregation": self.aggregation,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
