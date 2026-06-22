import { apiRequest } from '@/lib/api';

export interface MessageResponse {
  id: string;
  role: 'USER' | 'ASSISTANT' | 'SYSTEM';
  content: string;
  status: 'COMPLETE' | 'TRUNCATED';
  created_at: string;
}

export interface ChatResponse {
  id: string;
  title: string;
  document_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ChatDetailResponse extends ChatResponse {
  messages: MessageResponse[];
  missing_document_ids: string[];
}

export interface ChatListResponse {
  items: ChatResponse[];
  total: number;
  limit: number;
  offset: number;
  pages: number;
}

export async function createChat(document_ids: string[]): Promise<ChatResponse> {
  return apiRequest<ChatResponse>('/chats', {
    method: 'POST',
    body: JSON.stringify({ document_ids }),
  });
}

export async function listChats(limit = 20, offset = 0): Promise<ChatListResponse> {
  return apiRequest<ChatListResponse>(`/chats?limit=${limit}&offset=${offset}`);
}

export async function getChat(chat_id: string): Promise<ChatDetailResponse> {
  return apiRequest<ChatDetailResponse>(`/chats/${chat_id}`);
}

export async function renameChat(chat_id: string, title: string): Promise<ChatResponse> {
  return apiRequest<ChatResponse>(`/chats/${chat_id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

export async function deleteChat(chat_id: string): Promise<void> {
  return apiRequest<void>(`/chats/${chat_id}`, {
    method: 'DELETE',
  });
}
