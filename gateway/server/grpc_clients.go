package main

import (
	"common/types"
	"log"
	userpb "user_service/pb"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func InitGRPCClients(serviceMap map[string]string) *types.GRPCClients {
	conn, err := grpc.NewClient(serviceMap["user"], grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("failed to connect to UserService: %v", err)
	}
	return &types.GRPCClients{
		UserService: userpb.NewUserServiceClient(conn),
	}
}
