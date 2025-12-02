package types

import (
	userpb "user_service/pb"
)

type GRPCClients struct {
	UserService userpb.UserServiceClient
}
