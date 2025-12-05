package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/idebenone/gum/common/client"
)

func AddObservationHandler(grpcClients *client.GRPCClients) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var payload struct {
			UserID       string  `json:"user_id"`
			Observation  string  `json:"observation"`
			Value        float64 `json:"value"`
			ObserverName string  `json:"observer_name,omitempty"`
			ContentType  string  `json:"content_type,omitempty"`
			ID           string  `json:"id,omitempty"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		obs := &client.Observation{
			UserId:       payload.UserID,
			Content:      payload.Observation,
			ObserverName: payload.ObserverName,
			ContentType:  payload.ContentType,
			Id:           payload.ID,
		}

		req := &client.AddObservationsRequest{
			Observations: []*client.Observation{obs},
		}

		resp, err := grpcClients.GumService.AddObservations(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}
