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

function statusBadge(status: string) {
  if (status === "waiting_agent_response") {
    return "bg-amber-100 text-amber-800";
  }
  if (status === "closed") {
    return "bg-gray-100 text-gray-600";
  }
  return "bg-green-100 text-green-800";
}

export default function EmailsPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    async function loadConversations() {
      try {
        setConversations(await listConversations("email"));
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
    setSendError(null);
    try {
      await replyToConversation(selectedId, text, AGENT_NAME);
      setReply("");
    } catch (err) {
      // This reply is emailed to the customer, so a failure here means they
      // received nothing. Say so, and leave the text in the box to retry --
      // clearing it silently would look exactly like a successful send.
      setSendError(
        err instanceof Error ? err.message : "The reply could not be sent."
      );
    } finally {
      setSending(false);
    }

    // Refresh either way: on failure the message is still persisted, stamped
    // as undelivered, and the agent needs to see it in that state.
    try {
      const { messages: serverMessages } = await getConversation(selectedId);
      setMessages(serverMessages);
      setConversations(await listConversations("email"));
    } catch {
      // The pollers will catch up.
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-gray-50">
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-gray-900">Emails</h1>
      </header>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-80 shrink-0 overflow-y-auto border-r border-gray-200 bg-white">
          {conversations.length === 0 && (
            <p className="p-4 text-sm text-gray-500">No email conversations yet.</p>
          )}
          {conversations.map((conv) => (
            <button
              key={conv.conversation_id}
              onClick={() => {
                setSelectedId(conv.conversation_id);
                setSendError(null);
              }}
              className={`block w-full border-b border-gray-100 p-4 text-left hover:bg-gray-50 ${
                selectedId === conv.conversation_id ? "bg-blue-50" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-gray-900">
                  {conv.customer_email ?? conv.customer_identifier ?? "Unknown sender"}
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${statusBadge(conv.status)}`}
                >
                  {conv.status === "waiting_agent_response" ? "needs reply" : conv.status}
                </span>
              </div>
              <p className="mt-1 truncate text-xs text-gray-500">
                {conv.last_message_preview}
              </p>
            </button>
          ))}
        </aside>

        <section className="flex min-h-0 flex-1 flex-col">
          {!selectedId && (
            <div className="flex flex-1 items-center justify-center text-sm text-gray-500">
              Select an email conversation
            </div>
          )}

          {selectedId && (
            <>
              <div className="flex-1 space-y-3 overflow-y-auto p-6">
                {messages.map((msg) => {
                  const undelivered = msg.delivery_status === "failed";
                  return (
                    <div
                      key={msg.message_id}
                      className={`max-w-2xl rounded-lg p-3 text-sm ${
                        msg.sender === "customer"
                          ? "bg-gray-100 text-gray-900"
                          : undelivered
                            ? "ml-auto border border-red-300 bg-red-50 text-gray-900"
                            : "ml-auto bg-blue-600 text-white"
                      }`}
                    >
                      <p className="mb-1 text-xs opacity-70">{msg.sender_name}</p>
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      {undelivered && (
                        <p className="mt-2 text-xs font-medium text-red-700">
                          ⚠ Not delivered — this email was never sent to the
                          customer.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="border-t border-gray-200 bg-white p-4">
                {sendError && (
                  <p
                    role="alert"
                    className="mb-2 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800"
                  >
                    {sendError}
                  </p>
                )}
                <div className="flex gap-2">
                  <textarea
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Reply by email…"
                    rows={2}
                    className="flex-1 resize-none rounded border border-gray-300 p-2 text-sm"
                  />
                  <button
                    onClick={handleReply}
                    disabled={sending || !reply.trim()}
                    className="rounded bg-blue-600 px-4 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {sending ? "Sending…" : "Send"}
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
