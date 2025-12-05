package main

import (
	"context"
	"fmt"
	"log"
	"net/http"

	"github.com/idebenone/gum/common/client"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "github.com/idebenone/gum/gateway/server/pb"
)

var serviceMap = map[string]string{
	"user": "localhost:6001",
	"gum":  "localhost:6002",
}

type ActionServiceServer struct {
	pb.UnimplementedActionServiceServer
}

type UserGatewayServer struct {
	client.UnimplementedUserServiceServer
}
type GumGatewayServer struct {
	client.UnimplementedGumServiceServer
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

func (s UserGatewayServer) RegisterUser(ctx context.Context, req *client.RegisterUserRequest) (*client.UserServiceResponse, error) {
	conn, err := grpc.NewClient(serviceMap["user"], grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to UserService: %v", err)
	}
	defer conn.Close()
	client := client.NewUserServiceClient(conn)
	return client.RegisterUser(ctx, req)
}

func (s UserGatewayServer) LoginUser(ctx context.Context, req *client.LoginUserRequest) (*client.UserServiceResponse, error) {
	conn, err := grpc.NewClient(serviceMap["user"], grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to UserService: %v", err)
	}
	defer conn.Close()
	client := client.NewUserServiceClient(conn)
	return client.LoginUser(ctx, req)
}

func (g GumGatewayServer) SubmitObservation(ctx context.Context, req *client.AddObservationsRequest) (*client.AddObservationsResponse, error) {
	conn, err := grpc.NewClient(serviceMap["gum"], grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to GumService: %v", err)
	}
	defer conn.Close()
	client := client.NewGumServiceClient(conn)
	return client.AddObservations(ctx, req)
}

func main() {
	serviceMap := map[string]string{
		"user": "localhost:6001",
		"gum":  "localhost:6002",
	}
	grpcClients := InitGRPCClients(serviceMap)
	router := SetupRoutes(grpcClients)
	httpPort := ":8080"
	log.Printf("HTTP API Gateway listening on %s", httpPort)
	if err := http.ListenAndServe(httpPort, router); err != nil {
		log.Fatalf("failed to start HTTP server: %v", err)
	}
}
