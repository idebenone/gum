import { useState } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router";
import { useSetAtom } from "jotai";

import { Eye, EyeOff } from "lucide-react";
import { authenticateUser } from "@/api/auth";
import { authTokenAtom } from "@/lib/atoms";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Loader from "@/components/loader";

export default function AuthPage() {
  const [username, setUsername] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const navigate = useNavigate();
  const setAuthToken = useSetAtom(authTokenAtom);

  async function handleAuth() {
    try {
      setIsLoading(true);
      const response = await authenticateUser(username, password);
      setAuthToken(response.access_token);
      toast.success("Logged in successfully!");
      navigate("/");
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex h-full w-full justify-center items-center">
      <div className="flex flex-col gap-2">
        <p className="text-center font-bold text-3xl under">zornal .</p>
        <Input
          placeholder="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="placeholder:italic"
        />
        <div className="relative">
          <Input
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type={showPassword ? "text" : "password"}
            className="placeholder:italic"
          />
          <span className="absolute right-2 top-1/2 transform -translate-y-1/2">
            {showPassword ? (
              <Eye
                className="cursor-pointer h-4 w-4"
                onClick={() => setShowPassword(false)}
              />
            ) : (
              <EyeOff
                className="cursor-pointer h-4 w-4"
                onClick={() => setShowPassword(true)}
              />
            )}
          </span>
        </div>
        {isLoading ? (
          <Loader />
        ) : (
          <Button
            disabled={isLoading || !username || !password}
            onClick={handleAuth}
            className="italic"
          >
            Login
          </Button>
        )}
      </div>
    </div>
  );
}
