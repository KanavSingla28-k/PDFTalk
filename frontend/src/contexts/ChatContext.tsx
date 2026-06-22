'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { ChatResponse, ChatDetailResponse, MessageResponse, listChats, createChat, getChat, renameChat as renameChatApi, deleteChat as deleteChatApi } from '@/lib/chats.api';
import { streamAnswer, StreamEvent } from '@/lib/query.api';
import { useAuth } from './AuthContext';
import { showToast } from '@/lib/toast';

interface ChatContextValue {
  chats: ChatResponse[];
  activeChat: ChatDetailResponse | null;
  isLoadingChats: boolean;
  isStreaming: boolean;
  createNewChat: (document_ids: string[]) => Promise<string>;
  loadChat: (chat_id: string) => Promise<void>;
  sendMessage: (question: string) => Promise<void>;
  renameChat: (chat_id: string, title: string) => Promise<void>;
  deleteChat: (chat_id: string) => Promise<void>;
  abortStream: () => void;
  refreshChats: () => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [chats, setChats] = useState<ChatResponse[]>([]);
  const [activeChat, setActiveChat] = useState<ChatDetailResponse | null>(null);
  const [isLoadingChats, setIsLoadingChats] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [abortController, setAbortController] = useState<AbortController | null>(null);

  const refreshChats = useCallback(async () => {
    if (!user) return;
    setIsLoadingChats(true);
    try {
      const res = await listChats(50, 0);
      setChats(res.items);
    } catch (e) {
      console.error(e);
      showToast.error('Failed to load chats');
    } finally {
      setIsLoadingChats(false);
    }
  }, [user]);

  useEffect(() => {
    refreshChats();
  }, [refreshChats]);

  const createNewChat = async (document_ids: string[]) => {
    const chat = await createChat(document_ids);
    setChats(prev => [chat, ...prev]);
    const detail: ChatDetailResponse = { ...chat, messages: [], missing_document_ids: [] };
    setActiveChat(detail);
    return chat.id;
  };

  const loadChat = async (chat_id: string) => {
    try {
      const chat = await getChat(chat_id);
      setActiveChat(chat);
    } catch (e) {
      console.error(e);
      showToast.error('Failed to load chat details');
      throw e;
    }
  };

  const renameChat = async (chat_id: string, title: string) => {
    try {
      const updated = await renameChatApi(chat_id, title);
      setChats(prev => prev.map(c => c.id === chat_id ? { ...c, title: updated.title } : c));
      if (activeChat?.id === chat_id) {
        setActiveChat(prev => prev ? { ...prev, title: updated.title } : prev);
      }
    } catch (e) {
      console.error(e);
      showToast.error('Failed to rename chat');
      throw e;
    }
  };

  const deleteChat = async (chat_id: string) => {
    try {
      await deleteChatApi(chat_id);
      setChats(prev => prev.filter(c => c.id !== chat_id));
      if (activeChat?.id === chat_id) {
        setActiveChat(null);
      }
    } catch (e) {
      console.error(e);
      showToast.error('Failed to delete chat');
      throw e;
    }
  };

  const abortStream = useCallback(() => {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
      setIsStreaming(false);
    }
  }, [abortController]);

  const sendMessage = async (question: string) => {
    if (!activeChat) return;

    // Create a temporary user message
    const tempUserId = `temp-user-${Date.now()}`;
    const userMessage: MessageResponse = {
      id: tempUserId,
      role: 'USER',
      content: question,
      status: 'COMPLETE',
      created_at: new Date().toISOString()
    };

    // Create a temporary assistant message that will be streamed into
    const tempAssistantId = `temp-assistant-${Date.now()}`;
    const assistantMessage: MessageResponse = {
      id: tempAssistantId,
      role: 'ASSISTANT',
      content: '',
      status: 'COMPLETE',
      created_at: new Date().toISOString()
    };

    setActiveChat(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: [...prev.messages, userMessage, assistantMessage]
      };
    });

    const controller = new AbortController();
    setAbortController(controller);
    setIsStreaming(true);

    try {
      await streamAnswer(
        { chat_id: activeChat.id, question },
        (event: StreamEvent) => {
          if (event.type === 'meta') {
             setActiveChat(prev => {
                 if (!prev) return prev;
                 return { ...prev, missing_document_ids: event.missing_document_ids };
             });
          } else if (event.type === 'token') {
            setActiveChat(prev => {
              if (!prev) return prev;
              const newMessages = [...prev.messages];
              const lastMsg = newMessages[newMessages.length - 1];
              if (lastMsg.id === tempAssistantId) {
                lastMsg.content += event.content;
              }
              return { ...prev, messages: newMessages };
            });
          } else if (event.type === 'done') {
            setIsStreaming(false);
            setAbortController(null);
            // Refresh chats list to get updated title/updated_at
            refreshChats();
          } else if (event.type === 'error') {
            showToast.error(event.message);
            setIsStreaming(false);
            setAbortController(null);
          }
        },
        controller.signal
      );
    } catch (e) {
      console.error(e);
      setIsStreaming(false);
      setAbortController(null);
    }
  };

  return (
    <ChatContext.Provider
      value={{
        chats,
        activeChat,
        isLoadingChats,
        isStreaming,
        createNewChat,
        loadChat,
        sendMessage,
        renameChat,
        deleteChat,
        abortStream,
        refreshChats,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
}
