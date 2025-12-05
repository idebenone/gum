package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/idebenone/gum/common/client"

	"google.golang.org/protobuf/types/known/timestamppb"
)

func RegisterUserHandler(grpcClients *client.GRPCClients) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var payload struct {
			Username  string `json:"username"`
			Password  string `json:"password"`
			Email     string `json:"email"`
			FirstName string `json:"first_name"`
			LastName  string `json:"last_name"`
			DOB       string `json:"dob"`
			Gender    string `json:"gender"`
			Place     string `json:"place"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}
		var dobTimestamp *timestamppb.Timestamp
		if payload.DOB != "" {
			parsedDOB, err := time.Parse(time.RFC3339, payload.DOB)
			if err != nil {
				http.Error(w, "Invalid dob format, must be RFC3339", http.StatusBadRequest)
				return
			}
			dobTimestamp = timestamppb.New(parsedDOB)
		}
		req := &client.RegisterUserRequest{
			Username:  payload.Username,
			Password:  payload.Password,
			Email:     payload.Email,
			FirstName: payload.FirstName,
			LastName:  payload.LastName,
			Dob:       dobTimestamp,
			Gender:    payload.Gender,
			Place:     payload.Place,
		}
		resp, err := grpcClients.UserService.RegisterUser(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

func LoginUserHandler(grpcClients *client.GRPCClients) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var payload struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}
		req := &client.LoginUserRequest{
			Username: payload.Username,
			Password: payload.Password,
		}
		resp, err := grpcClients.UserService.LoginUser(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

func ProtectedHelloHandler(w http.ResponseWriter, r *http.Request) {
	resp := map[string]string{"message": "Hello, authenticated user!"}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
