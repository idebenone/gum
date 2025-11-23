import { useEffect, type ReactNode } from "react";
import { useAtomValue } from "jotai";
import { useLocation, useNavigate } from "react-router";
import { authTokenAtom } from "../atoms";

interface Props {
  children: ReactNode;
}

export const AuthProvider = ({ children }: Props) => {
  const token = useAtomValue(authTokenAtom);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!token) {
      if (location.pathname !== "/auth") {
        navigate("/auth", { replace: true });
      }
    } else {
      if (location.pathname === "/auth") {
        navigate("/", { replace: true });
      }
    }
  }, [token, location.pathname]);

  return <>{children}</>;
};
