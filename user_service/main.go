package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/anypb"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"common/entities"
	pb "user_service/pb"
)

var jwtSecret = []byte("supersecretkey")

type UserServiceServer struct {
	pb.UnimplementedUserServiceServer
	db *gorm.DB
}

func hashPassword(password string) (string, error) {
	bytes, err := bcrypt.GenerateFromPassword([]byte(password), 14)
	return string(bytes), err
}

func checkPasswordHash(password, hash string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

func (s *UserServiceServer) RegisterUser(ctx context.Context, req *pb.RegisterUserRequest) (*pb.UserServiceResponse, error) {
	hash, err := hashPassword(req.Password)
	if err != nil {
		return nil, fmt.Errorf("failed to hash password: %v", err)
	}
	user := entities.User{
		ID:        fmt.Sprintf("user-%d", time.Now().UnixNano()),
		Username:  req.Username,
		Email:     req.Email,
		Password:  hash,
		FirstName: req.FirstName,
		LastName:  req.LastName,
		DOB:       req.Dob.AsTime(),
		Place:     req.Place,
		Gender:    req.Gender,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := s.db.Create(&user).Error; err != nil {
		return nil, fmt.Errorf("failed to create user: %v", err)
	}
	return &pb.UserServiceResponse{ResponseTime: time.Now().Format(time.RFC3339), ErrorStatus: false, Message: "user registration successful", Data: nil}, nil
}

func (s *UserServiceServer) LoginUser(ctx context.Context, req *pb.LoginUserRequest) (*pb.UserServiceResponse, error) {
	var user entities.User
	if err := s.db.Where("username = ?", req.Username).First(&user).Error; err != nil {
		return nil, fmt.Errorf("user not found")
	}
	if !checkPasswordHash(req.Password, user.Password) {
		return nil, fmt.Errorf("invalid credentials")
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":      user.ID,
		"username": user.Username,
		"exp":      time.Now().Add(time.Hour * 72).Unix(),
	})
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		return nil, fmt.Errorf("failed to sign token: %v", err)
	}
	tokenAny, err := anypb.New(&pb.Token{Token: tokenString})
	if err != nil {
		return nil, fmt.Errorf("failed to marshal token: %v", err)
	}
	return &pb.UserServiceResponse{ResponseTime: time.Now().Format(time.RFC3339), ErrorStatus: false, Message: "login successful", Data: tokenAny}, nil
}

func (s *UserServiceServer) LogoutUser(ctx context.Context, req *pb.LogoutUserRequest) (*pb.UserServiceResponse, error) {
	return &pb.UserServiceResponse{ResponseTime: time.Now().Format(time.RFC3339), ErrorStatus: false, Message: "logout successful", Data: nil}, nil
}

func main() {
	dsn := "host=localhost user=postgres password=root dbname=gum port=5432 sslmode=disable"
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("failed to connect database: %v", err)
	}
	db.AutoMigrate(&entities.User{})

	port := os.Getenv("USER_SERVICE_PORT")
	if port == "" {
		port = "6001"
	}
	lis, err := net.Listen("tcp", ":"+port)
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}
	grpcServer := grpc.NewServer()
	pb.RegisterUserServiceServer(grpcServer, &UserServiceServer{db: db})
	log.Printf("UserService listening on :%s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
