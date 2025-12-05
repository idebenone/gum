module github.com/idebenone/gum/gateway/server

go 1.24.3

require (
	github.com/idebenone/gum/common v0.0.0
	google.golang.org/grpc v1.77.0
	google.golang.org/protobuf v1.36.10
)

require (
	github.com/idebenone/gum/gum_service v0.0.0 // indirect
	github.com/idebenone/gum/user_service v0.0.0 // indirect
)

require (
	github.com/golang-jwt/jwt v3.2.2+incompatible
	golang.org/x/net v0.47.0 // indirect
	golang.org/x/sys v0.38.0 // indirect
	golang.org/x/text v0.31.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20251124214823-79d6a2a48846 // indirect
)

replace github.com/idebenone/gum/common => ../../common

replace github.com/idebenone/gum/gum_service => ../../gum_service

replace github.com/idebenone/gum/user_service => ../../user_service
