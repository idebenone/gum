package main

import (
	"context"
	"fmt"
	"log"
	"net/http"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "gateway/pb"
	userpb "user_service/pb"
)

var serviceMap = map[string]string{
	"user": "localhost:6001",
}

type ActionServiceServer struct {
	pb.UnimplementedActionServiceServer
}

type UserGatewayServer struct {
	userpb.UnimplementedUserServiceServer
}

func (s *ActionServiceServer) CreateAction(ctx context.Context, req *pb.CreateActionRequest) (*pb.ActionResponse, error) {
	return &pb.ActionResponse{Action: req.Action}, nil
}

func (s *ActionServiceServer) GetActions(ctx context.Context, req *pb.GetActionsRequest) (*pb.GetActionsResponse, error) {
	return &pb.GetActionsResponse{}, nil
}

func (s *ActionServiceServer) UpdateActionState(ctx context.Context, req *pb.UpdateActionStateRequest) (*pb.ActionResponse, error) {
	return &pb.ActionResponse{}, nil
}

func (s *UserGatewayServer) RegisterUser(ctx context.Context, req *userpb.RegisterUserRequest) (*userpb.UserServiceResponse, error) {
	conn, err := grpc.NewClient(serviceMap["user"], grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to UserService: %v", err)
	}
	defer conn.Close()
	client := userpb.NewUserServiceClient(conn)
	return client.RegisterUser(ctx, req)
}

func main() {
	serviceMap := map[string]string{
		"user": "localhost:6001",
	}
	grpcClients := InitGRPCClients(serviceMap)
	router := SetupRoutes(grpcClients)
	httpPort := ":8080"
	log.Printf("HTTP API Gateway listening on %s", httpPort)
	if err := http.ListenAndServe(httpPort, router); err != nil {
		log.Fatalf("failed to start HTTP server: %v", err)
	}
}
