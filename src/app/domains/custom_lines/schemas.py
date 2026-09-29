from pydantic import BaseModel, Field

from app.transport.http.schemas import BaseResponse


class CustomLineSubmitRequest(BaseModel):
    """自定义线路提交请求模型"""

    domain: str = Field(..., min_length=1, max_length=255, description="线路域名")
    network_info: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="三网线路情况（电信/联通/移动等）",
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str = Field(
        default="one_way",
        description="流量计算类型: one_way=单向, two_way=双向",
    )
    total_traffic: float = Field(..., gt=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool = Field(default=False, description="是否长期可用")
    user_note: str | None = Field(None, max_length=500, description="用户备注")


class CustomLineInfo(BaseModel):
    """自定义线路信息模型"""

    id: int
    tg_id: int
    domain: str
    network_info: str
    price_monthly: float | None = None
    price_yearly: float | None = None
    traffic_limit: float | None = None
    traffic_type: str
    valid_days: int | None = None
    is_permanent: bool
    status: str
    admin_note: str | None = None
    user_note: str | None = None
    tags: list[str] | None = None
    approved_at: int | None = None
    approved_by: int | None = None
    expires_at: int | None = None
    created_at: int
    updated_at: int
    total_traffic: float | None = None


class CustomLineListResponse(BaseResponse):
    """自定义线路列表响应模型"""

    lines: list[CustomLineInfo] = Field(default=[])
    total: int = 0


class CustomLineDetailResponse(BaseResponse):
    """自定义线路详情响应模型"""

    line: CustomLineInfo | None = None


class CustomLineApproveRequest(BaseModel):
    """管理员审批自定义线路请求模型"""

    action: str = Field(..., description="审批动作: approve=批准, reject=拒绝")
    admin_note: str | None = Field(None, max_length=500, description="管理员备注")
    valid_days: int | None = Field(
        None, ge=1, description="管理员设定的有效天数（覆盖用户提交的值）"
    )
    is_permanent: bool | None = Field(
        None, description="是否设为长期可用（覆盖用户提交的值）"
    )


class CustomLineUpdateRequest(BaseModel):
    """更新自定义线路请求模型（用户或管理员）"""

    domain: str | None = Field(
        None, min_length=1, max_length=255, description="线路域名"
    )
    network_info: str | None = Field(
        None, min_length=1, max_length=500, description="三网线路情况"
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str | None = Field(None, description="流量计算类型")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
    user_note: str | None = Field(None, max_length=500, description="用户备注")


class AdminCustomLineUpdateRequest(BaseModel):
    """管理员更新自定义线路请求模型"""

    domain: str | None = Field(
        None, min_length=1, max_length=255, description="线路域名"
    )
    network_info: str | None = Field(
        None, min_length=1, max_length=500, description="三网线路情况"
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str | None = Field(None, description="流量计算类型")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
    admin_note: str | None = Field(None, max_length=500, description="管理员备注")
    status: str | None = Field(
        None,
        description="状态: pending=待审核/approved=已批准/rejected=已拒绝/offline=已下线/expired=已过期",
    )


class CustomLineRenewRequest(BaseModel):
    """续期自定义线路请求模型"""

    valid_days: int = Field(..., ge=1, le=365 * 3, description="续期天数（1-1095天）")


class CustomLineOnlineRequest(BaseModel):
    """上线自定义线路请求模型"""

    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
