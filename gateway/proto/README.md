# Unified gRPC API Schema for gum Platform

This directory will contain all protobuf (`.proto`) files defining the API contracts for your services.

- Start with `action_service.proto` for action items and orchestration.
- Add more proto files for calendar, notification, task, etc. as you grow.

---

## Example: action_service.proto

```
syntax = "proto3";

package gum;

service ActionService {
  rpc CreateAction (CreateActionRequest) returns (ActionResponse);
  rpc GetActions (GetActionsRequest) returns (GetActionsResponse);
  rpc UpdateActionState (UpdateActionStateRequest) returns (ActionResponse);
}

message CreateActionRequest {
  string user_id = 1;
  ActionItem action = 2;
}

message GetActionsRequest {
  string user_id = 1;
  string state = 2; // e.g., "pending", "completed"
}

message UpdateActionStateRequest {
  string action_id = 1;
  string new_state = 2;
}

message ActionItem {
  string id = 1;
  string type = 2; // e.g., "reminder", "calendar_event"
  string description = 3;
  string category = 4; // e.g., "Calendar", "Notification"
  string payload = 5; // JSON or structured data
  string state = 6; // "pending", "done", etc.
  string created_at = 7;
  string updated_at = 8;
}

message ActionResponse {
  ActionItem action = 1;
}

message GetActionsResponse {
  repeated ActionItem actions = 1;
}
```

---

Add your `.proto` files here and keep them versioned!
