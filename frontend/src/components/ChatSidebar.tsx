'use client';

import React from 'react';
import { useChat } from '@/contexts/ChatContext';
import { Button } from '@/components/ui';

export function ChatSidebar() {
  const { chats, activeChat, loadChat, deleteChat, isLoadingChats } = useChat();

  return (
    <div className="w-64 border-r border-[var(--gray-200)] bg-[var(--gray-50)] h-full flex flex-col p-4">
      <div className="mb-4 font-semibold text-[var(--gray-900)]">Chats</div>
      
      {isLoadingChats ? (
        <div className="text-sm text-[var(--gray-500)]">Loading...</div>
      ) : (
        <div className="flex-1 overflow-y-auto flex flex-col gap-2">
          {chats.map(chat => (
            <div
              key={chat.id}
              onClick={() => loadChat(chat.id)}
              className={`p-3 rounded-lg cursor-pointer text-sm border flex justify-between items-center group
                ${activeChat?.id === chat.id 
                  ? 'bg-[var(--brand-50)] border-[var(--brand-500)] text-[var(--brand-700)]' 
                  : 'bg-white border-[var(--gray-200)] hover:border-[var(--gray-300)]'
                }
              `}
            >
              <div className="truncate max-w-[140px]" title={chat.title}>
                {chat.title}
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 text-[var(--gray-400)] hover:text-red-500 transition-opacity"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm('Are you sure you want to delete this chat?')) {
                    deleteChat(chat.id);
                  }
                }}
              >
                ×
              </button>
            </div>
          ))}
          {chats.length === 0 && (
            <div className="text-sm text-[var(--gray-500)]">No chats yet</div>
          )}
        </div>
      )}
    </div>
  );
}
