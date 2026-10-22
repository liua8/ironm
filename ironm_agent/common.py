"""公共部分：契约基类。"""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """契约基类：不可变、拒绝未定义字段、不做类型宽松转换、拒绝 NaN 与无穷。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)
