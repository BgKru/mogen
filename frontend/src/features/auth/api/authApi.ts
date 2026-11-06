import { apiClient } from "../../../shared/api/client";
import { mapUser } from "../../../shared/api/mappers";
import type { AuthResponseDto, CsrfResponseDto, UserDto } from "../../../shared/api/dto";
import type { LoginInput, RegisterInput, User } from "../../../shared/types/api";

export async function fetchCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<UserDto>("/auth/me");
  return mapUser(data);
}

export async function fetchCsrfToken(): Promise<string> {
  const { data } = await apiClient.get<CsrfResponseDto>("/auth/csrf");
  return data.csrf_token;
}

export async function registerUser(input: RegisterInput): Promise<User> {
  const { data } = await apiClient.post<AuthResponseDto>("/auth/register", input);
  return mapUser(data.user);
}

export async function loginUser(input: LoginInput): Promise<User> {
  const { data } = await apiClient.post<AuthResponseDto>("/auth/login", input);
  return mapUser(data.user);
}

export async function logoutUser(): Promise<void> {
  await apiClient.post("/auth/logout");
}
