package main

import (
	"common/types"
	"gateway/handlers"
	"net/http"
)

func SetupRoutes(grpcClients *types.GRPCClients) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/register", handlers.RegisterUserHandler(grpcClients))
	mux.HandleFunc("/api/login", handlers.LoginUserHandler(grpcClients))
	// Add more routes here as you add more services
	return mux
}
