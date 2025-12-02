module gateway

go 1.24.3

require (
	common v0.0.0
	github.com/golang-jwt/jwt/v5 v5.3.0
	google.golang.org/grpc v1.77.0
	google.golang.org/protobuf v1.36.10
	user_service v0.0.0
)

require (
	github.com/golang-jwt/jwt v3.2.2+incompatible
	golang.org/x/net v0.47.0 // indirect
	golang.org/x/sys v0.38.0 // indirect
	golang.org/x/text v0.31.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20251124214823-79d6a2a48846 // indirect
)

replace user_service => ../../user_service

replace common => ../../common
