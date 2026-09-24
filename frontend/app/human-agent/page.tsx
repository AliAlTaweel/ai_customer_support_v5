"use client";

import { useEffect, useState } from "react";
import {
  ConversationSummary,
  Message,
  getConversation,
  listConversations,
  replyToConversation,
} from "@/lib/api";

const POLL_INTERVAL_MS = 4000;
const AGENT_NAME = "Support Agent";

export default function HumanAgentPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    async function loadConversations() {
      try {
        const data = await listConversations();
        setConversations(data);
      } catch {
        // Silently retry on the next tick.
      }
    }

    loadConversations();
    const interval = setInterval(loadConversations, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      return;
    }

    async function loadThread() {
      try {
        const { messages: serverMessages } = await getConversation(selectedId!);
        setMessages(serverMessages);
      } catch {
        // Silently retry on the next tick.
      }
    }

    loadThread();
    const interval = setInterval(loadThread, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [selectedId]);

  async function handleReply() {
    const text = reply.trim();
    if (!text || !selectedId || sending) return;

    setSending(true);
    try {
      await replyToConversation(selectedId, text, AGENT_NAME);
      setReply("");
      const { messages: serverMessages } = await getConversation(selectedId);
      setMessages(serverMessages);
      const data = await listConversations();
      setConversations(data);
    } catch {
      // Leave the draft in place so the agent can retry.
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-gray-50">
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-gray-900">Human Agent</h1>
      </header>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-80 shrink-0 overflow-y-auto border-r border-gray-200 bg-white">
          {conversations.length === 0 && (
            <p className="p-4 text-sm text-gray-400">No conversations yet.</p>
          )}
          {conversations.map((c) => (
            <button
              key={c.conversation_id}
              onClick={() => setSelectedId(c.conversation_id)}
              className={`flex w-full flex-col gap-1 border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50 ${
                selectedId === c.conversation_id ? "bg-blue-50" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900">
                  {c.customer_name || c.customer_email || "Guest"}
                </span>
                {c.status === "waiting_agent_response" && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                    Waiting
                  </span>
                )}
              </div>
              <span className="truncate text-xs text-gray-500">{c.last_message_preview}</span>
            </button>
          ))}
        </aside>

        <section className="flex min-h-0 flex-1 flex-col">
          {!selectedId ? (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-gray-400">Select a conversation to view it.</p>
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
                <div className="mx-auto flex max-w-2xl flex-col gap-3">
                  {messages.map((m) => (
                    <div
                      key={m.message_id}
                      className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${
                        m.sender === "customer"
                          ? "self-start bg-white text-gray-900 shadow-sm"
                          : m.sender === "ai"
                            ? "self-end bg-gray-200 text-gray-900"
                            : "self-end bg-blue-600 text-white"
                      }`}
                    >
                      {m.sender !== "customer" && (
                        <p className="mb-1 text-xs font-semibold opacity-70">
                          {m.sender === "ai" ? "AI Assistant" : m.sender_name}
                        </p>
                      )}
                      {m.content}
                    </div>
                  ))}
                </div>
              </div>

              <footer className="shrink-0 border-t border-gray-200 bg-white px-6 py-4">
                <div className="mx-auto flex max-w-2xl gap-2">
                  <input
                    className="flex-1 rounded-full border border-gray-300 px-4 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
                    placeholder="Type a reply…"
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleReply();
                    }}
                    disabled={sending}
                  />
                  <button
                    className="rounded-full bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
                    onClick={handleReply}
                    disabled={sending || !reply.trim()}
                  >
                    Send
                  </button>
                </div>
              </footer>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
