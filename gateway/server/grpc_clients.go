package main

import (
	"log"

	"github.com/idebenone/gum/common/client"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func mustNewClient(addr string) grpc.ClientConnInterface {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("failed to connect to %s: %v", addr, err)
	}
	return conn
}

func InitGRPCClients(serviceMap map[string]string) *client.GRPCClients {
	return &client.GRPCClients{
		UserService: client.NewUserServiceClient(mustNewClient(serviceMap["user"])),
		GumService:  client.NewGumServiceClient(mustNewClient(serviceMap["gum"])),
	}
}
