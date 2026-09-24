"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { getConversation, sendMessage } from "@/lib/api";

interface ChatMessage {
  id: string;
  sender: "customer" | "ai" | "agent" | "error";
  content: string;
}

const POLL_INTERVAL_MS = 4000;

const BULLET_RE = /^(\*|-|\d+\.)\s+/;

function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function FormattedMessage({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let listItems: string[] = [];

  function flushList() {
    if (listItems.length > 0) {
      blocks.push(
        <ul key={`list-${blocks.length}`} className="list-disc space-y-1 pl-5">
          {listItems.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const bulletMatch = line.match(BULLET_RE);
    if (bulletMatch) {
      listItems.push(line.slice(bulletMatch[0].length));
    } else {
      flushList();
      blocks.push(<p key={`p-${blocks.length}`}>{renderInline(line)}</p>);
    }
  }
  flushList();

  return <div className="flex flex-col gap-2">{blocks}</div>;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const seenMessageIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!conversationId) return;

    const interval = setInterval(async () => {
      try {
        const { messages: serverMessages } = await getConversation(conversationId);
        const newAgentMessages = serverMessages.filter(
          (m) => m.sender === "agent" && !seenMessageIds.current.has(m.message_id)
        );
        if (newAgentMessages.length === 0) return;

        newAgentMessages.forEach((m) => seenMessageIds.current.add(m.message_id));
        setMessages((prev) => [
          ...prev,
          ...newAgentMessages.map((m) => ({
            id: m.message_id,
            sender: "agent" as const,
            content: m.content,
          })),
        ]);
      } catch {
        // Silently retry on the next tick.
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [conversationId]);

  async function handleSend() {
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), sender: "customer", content: text },
    ]);
    setSending(true);

    try {
      const res = await sendMessage(text);
      setConversationId(res.conversation_id);
      seenMessageIds.current.add(res.message_id);
      setMessages((prev) => [
        ...prev,
        {
          id: res.message_id + "-ai",
          sender: "ai",
          content: res.ai_answer ?? "(no AI reply — a human will follow up)",
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          sender: "error",
          content: "Something went wrong sending your message. Please try again.",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-gray-50">
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-gray-900">AI Customer Support</h1>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto flex max-w-2xl flex-col gap-3">
          {messages.length === 0 && (
            <p className="mt-10 text-center text-sm text-gray-400">
              Send a message to start chatting.
            </p>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${
                m.sender === "customer"
                  ? "self-end bg-blue-600 text-white"
                  : m.sender === "error"
                    ? "self-start bg-red-100 text-red-700"
                    : m.sender === "agent"
                      ? "self-start bg-green-50 text-gray-900 shadow-sm"
                      : "self-start bg-white text-gray-900 shadow-sm"
              }`}
            >
              {m.sender === "agent" && (
                <p className="mb-1 text-xs font-semibold text-green-700">Support Agent</p>
              )}
              {m.sender === "ai" || m.sender === "agent" ? (
                <FormattedMessage content={m.content} />
              ) : (
                m.content
              )}
            </div>
          ))}
          {sending && (
            <div className="self-start rounded-2xl bg-white px-4 py-2 text-sm text-gray-400 shadow-sm">
              Typing…
            </div>
          )}
        </div>
      </main>

      <footer className="shrink-0 border-t border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            className="flex-1 rounded-full border border-gray-300 px-4 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
            placeholder="Type a message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSend();
            }}
            disabled={sending}
          />
          <button
            className="rounded-full bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
            onClick={handleSend}
            disabled={sending || !input.trim()}
          >
            Send
          </button>
        </div>
      </footer>
    </div>
  );
}
