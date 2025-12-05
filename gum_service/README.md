Inside Proto folder
python3 -m grpc_tools.protoc -I. --python_out=../pb --grpc_python_out=../pb gum_service.proto
