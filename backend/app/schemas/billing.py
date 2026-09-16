from pydantic import BaseModel


class VipUpgradeInitiationResponse(BaseModel):
    payment_url: str
    external_reference: str


class VipKycDocumentStartRequest(BaseModel):
    document_type: str = "sa_id"


class VipKycSdkTokenResponse(BaseModel):
    token: str
    job_id: str
