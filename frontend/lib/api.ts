const BACKEND_URL = "/api/backend";

export interface SendMessageResponse {
  success: boolean;
  conversation_id: string;
  message_id: string;
  created_at: string;
  ai_answer: string | null;
}

export async function sendMessage(message: string): Promise<SendMessageResponse> {
  const res = await fetch(`${BACKEND_URL}/chat/send`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      customer_name: "Guest",
    }),
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  return res.json();
}

export interface Message {
  message_id: string;
  sender: "customer" | "ai" | "agent";
  sender_name: string;
  content: string;
  read: boolean;
  created_at: string;
  /**
   * Only ever "failed", and only on an outbound reply whose send raised.
   * Absent/null means no outbound send was attempted or it succeeded.
   */
  delivery_status?: string | null;
}

export interface ConversationSummary {
  conversation_id: string;
  customer_email: string | null;
  customer_name: string | null;
  customer_identifier?: string | null;
  status: string;
  message_count: number;
  unread_count: number;
  last_message_at: string;
  last_message_preview: string;
  created_at: string;
}

export async function listConversations(
  channel?: string
): Promise<ConversationSummary[]> {
  const query = channel ? `?channel=${encodeURIComponent(channel)}` : "";
  const res = await fetch(`${BACKEND_URL}/chat/conversations${query}`);

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  const data = await res.json();
  return data.conversations;
}

export async function getConversation(
  conversationId: string
): Promise<{ conversation: ConversationSummary; messages: Message[] }> {
  const res = await fetch(`${BACKEND_URL}/chat/conversations/${conversationId}`);

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  return res.json();
}

export async function replyToConversation(
  conversationId: string,
  message: string,
  agentName = "Support Agent"
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/chat/conversations/${conversationId}/reply`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message, agent_name: agentName }),
  });

  if (!res.ok) {
    // The backend returns 502 with a human-readable detail when the reply was
    // saved but the email could not be sent. Surface that rather than a bare
    // status code, so the agent knows the customer did not receive it.
    let detail = "";
    try {
      detail = (await res.json())?.detail ?? "";
    } catch {
      // Non-JSON error body; fall back to the status code alone.
    }
    throw new Error(detail || `Request failed: ${res.status}`);
  }
}

export interface QAPair {
  qa_id: string;
  question: string;
  answer: string;
  updated_at: string;
}

export async function listQAPairs(): Promise<QAPair[]> {
  const res = await fetch(`${BACKEND_URL}/knowledge-base/qa-pairs`);

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  const data = await res.json();
  return data.qa_pairs;
}

export async function createQAPair(question: string, answer: string): Promise<QAPair> {
  const res = await fetch(`${BACKEND_URL}/knowledge-base/qa-pairs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, answer }),
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  return res.json();
}

export async function updateQAPair(
  qaId: string,
  question: string,
  answer: string
): Promise<QAPair> {
  const res = await fetch(`${BACKEND_URL}/knowledge-base/qa-pairs/${qaId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, answer }),
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }

  return res.json();
}

export async function deleteQAPair(qaId: string): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/knowledge-base/qa-pairs/${qaId}`, {
    method: "DELETE",
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
}
