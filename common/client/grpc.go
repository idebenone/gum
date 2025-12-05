package client

import (
	gumpb "github.com/idebenone/gum/gum_service/pb"
	userpb "github.com/idebenone/gum/user_service/pb"
	"google.golang.org/grpc"
)

type (
	UnimplementedUserServiceServer = userpb.UnimplementedUserServiceServer
	UnimplementedGumServiceServer  = gumpb.UnimplementedGumServiceServer

	UserServiceClient = userpb.UserServiceClient
	GumServiceClient  = gumpb.GumServiceClient

	RegisterUserRequest = userpb.RegisterUserRequest
	UserServiceResponse = userpb.UserServiceResponse
	LoginUserRequest    = userpb.LoginUserRequest

	AddObservationsRequest  = gumpb.AddObservationsRequest
	AddObservationsResponse = gumpb.AddObservationsResponse
	Observation             = gumpb.Observation
)

var (
	NewUserServiceClient func(cc grpc.ClientConnInterface) UserServiceClient = userpb.NewUserServiceClient
	NewGumServiceClient  func(cc grpc.ClientConnInterface) GumServiceClient  = gumpb.NewGumServiceClient
)

type GRPCClients struct {
	UserService UserServiceClient
	GumService  GumServiceClient
}
