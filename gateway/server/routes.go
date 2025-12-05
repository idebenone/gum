package main

import (
	"net/http"

	"github.com/idebenone/gum/gateway/server/handlers"

	"github.com/idebenone/gum/common/client"
)

func SetupRoutes(grpcClients *client.GRPCClients) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/register", handlers.RegisterUserHandler(grpcClients))
	mux.HandleFunc("/api/login", handlers.LoginUserHandler(grpcClients))
	mux.HandleFunc("/api/observation", handlers.AddObservationHandler(grpcClients))
	return mux
}
