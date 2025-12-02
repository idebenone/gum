import grpc
from concurrent import futures
from .pb import gum_service_pb2
from .pb import gum_service_pb2_grpc
from .services.redis_service import RedisObservationService
import asyncio
from .worker.redis_worker import _background_batch_processor
import os

class ObservationServiceServicer(gum_service_pb2_grpc.ObservationServiceServicer):
    def __init__(self, redis_service):
        self.redis_service = redis_service

    def AddObservations(self, request, context):
        try:
            for obs in request.observations:
                self.redis_service.add_observation(
                    user_id=getattr(obs, 'user_id', '0'),
                    observer_name=getattr(obs, 'observer_name', 'grpc_observer'),
                    content=getattr(obs, 'content', ''),
                    content_type=getattr(obs, 'content_type', 'text'),
                    observation_id=getattr(obs, 'id', None)
                )
            return gum_service_pb2.AddObservationsResponse(success=True, message="Observations added.")
        except Exception as e:
            return gum_service_pb2.AddObservationsResponse(success=False, message=str(e))


async def serve_async():
    server = grpc.aio.server()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_service = RedisObservationService(redis_url)
    gum_service_pb2_grpc.add_ObservationServiceServicer_to_server(
        ObservationServiceServicer(redis_service), server)
    server.add_insecure_port('[::]:50051')
    print("gRPC server started on port 50051.")
    await asyncio.gather(
        server.start(),
        _background_batch_processor(redis_service),
        server.wait_for_termination(),
    )

if __name__ == "__main__":
    asyncio.run(serve_async())
