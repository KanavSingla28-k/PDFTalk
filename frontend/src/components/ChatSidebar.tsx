'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useChat } from '@/contexts/ChatContext';
import { Button, Modal, Skeleton } from '@/components/ui';

export function ChatSidebar() {
  const { chats, activeChat, loadChat, deleteChat, renameChat, isLoadingChats, clearActiveChat } = useChat();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editingId]);

  const handleRenameSubmit = async (chatId: string) => {
    if (editValue.trim() !== '') {
      try {
        await renameChat(chatId, editValue.trim());
      } catch {
        // handle error silently, toast is shown in context
      }
    }
    setEditingId(null);
  };

  const [isMinimized, setIsMinimized] = useState(false);

  return (
    <>
    <div className={`border-r border-[var(--gray-200)] bg-[var(--gray-50)] h-full flex flex-col p-4 shrink-0 transition-all duration-300 ${isMinimized ? 'w-16 items-center' : 'w-64'}`}>
      <div className={`flex items-center w-full mb-4 ${isMinimized ? 'justify-center' : 'justify-between'}`}>
        {!isMinimized && <div className="font-semibold text-[var(--gray-900)]">Chats</div>}
        <button
          onClick={() => setIsMinimized(!isMinimized)}
          className="p-1 rounded-md text-[var(--gray-500)] hover:bg-[var(--gray-200)] hover:text-[var(--gray-900)] transition-colors"
          title={isMinimized ? "Expand sidebar" : "Minimize sidebar"}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {isMinimized ? (
              <path d="M13 17l5-5-5-5M6 17l5-5-5-5" />
            ) : (
              <path d="M11 17l-5-5 5-5M18 17l-5-5 5-5" />
            )}
          </svg>
        </button>
      </div>
      
      {!isMinimized && (
        <div className="mb-4">
          <Button 
            className="w-full flex items-center justify-center gap-2" 
            onClick={clearActiveChat}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            New Chat
          </Button>
        </div>
      )}

      {!isMinimized && (
        isLoadingChats ? (
          <div className="flex-1 flex flex-col gap-2 p-1">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full opacity-70" />
            <Skeleton className="h-10 w-full opacity-40" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto flex flex-col gap-2">
            {chats.map(chat => (
              <div
                key={chat.id}
                onClick={() => {
                  if (editingId !== chat.id && deletingId !== chat.id) loadChat(chat.id);
                }}
                className={`p-3 rounded-lg cursor-pointer text-sm border flex justify-between items-center group
                  ${activeChat?.id === chat.id 
                    ? 'bg-[var(--brand-50)] border-[var(--brand-500)] text-[var(--brand-700)]' 
                    : 'bg-[var(--surface-card)] border-[var(--gray-200)] hover:border-[var(--gray-300)]'
                  }
                `}
              >
                {editingId === chat.id ? (
                  <input
                    ref={inputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => handleRenameSubmit(chat.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRenameSubmit(chat.id);
                      if (e.key === 'Escape') setEditingId(null);
                    }}
                    className="w-full bg-[var(--surface-card)] border border-[var(--brand-500)] rounded px-1 outline-none text-[var(--gray-900)] max-w-[140px]"
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <div className="truncate max-w-[140px]" title={chat.title}>
                    {chat.title}
                  </div>
                )}
                
                {editingId !== chat.id && (
                  <div className="flex items-center shrink-0">
                    <button
                      className="opacity-0 group-hover:opacity-100 text-[var(--gray-400)] hover:text-[var(--brand-500)] transition-opacity mr-2"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(chat.id);
                        setEditValue(chat.title);
                      }}
                      title="Rename chat"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 20h9"></path>
                        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                      </svg>
                    </button>
                    <button
                      className="opacity-0 group-hover:opacity-100 text-[var(--gray-400)] hover:text-red-500 transition-opacity"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeletingId(chat.id);
                      }}
                      title="Delete chat"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 6h18"></path>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            ))}
            {chats.length === 0 && (
              <div className="text-sm text-[var(--gray-500)]">No chats yet</div>
            )}
          </div>
        )
      )}
    </div>
      
      <Modal 
        isOpen={!!deletingId} 
        onClose={() => setDeletingId(null)}
        title="Delete Chat"
        maxWidth="sm"
      >
        <div className="p-6 pt-2">
          <p className="text-sm text-[var(--gray-500)] mb-6">
            Are you sure you want to delete this chat? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <Button 
              variant="secondary" 
              onClick={() => setDeletingId(null)}
            >
              Cancel
            </Button>
            <Button 
              variant="danger" 
              onClick={() => {
                if (deletingId) deleteChat(deletingId);
                setDeletingId(null);
              }}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
