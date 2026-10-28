from fastapi import Request
from src.services.meter_service import MeterService


def get_meter_service(request: Request) -> MeterService:
    return request.app.state.meter_service
