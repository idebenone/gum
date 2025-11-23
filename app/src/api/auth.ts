const URL =
  import.meta.env.NODE_ENV === "production" ? "" : "http://localhost:8000";

export async function authenticateUser(username: string, password: string) {
  const res = await fetch(`${URL}/api/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error("Invalid credentials");
  }
  return res.json();
}
