"use client";

import { useEffect, useState } from "react";
import { createQAPair, deleteQAPair, listQAPairs, updateQAPair, QAPair } from "@/lib/api";

export default function KnowledgeBasePage() {
  const [pairs, setPairs] = useState<QAPair[]>([]);
  const [loading, setLoading] = useState(true);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editQuestion, setEditQuestion] = useState("");
  const [editAnswer, setEditAnswer] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function loadPairs() {
    setLoading(true);
    try {
      const data = await listQAPairs();
      setPairs(data);
      setError(null);
    } catch {
      setError("Failed to load knowledge base.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPairs();
  }, []);

  async function handleAdd() {
    if (!question.trim() || !answer.trim() || saving) return;
    setSaving(true);
    try {
      await createQAPair(question.trim(), answer.trim());
      setQuestion("");
      setAnswer("");
      await loadPairs();
      setError(null);
    } catch {
      setError("Failed to add Q&A pair.");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(p: QAPair) {
    setEditingId(p.qa_id);
    setEditQuestion(p.question);
    setEditAnswer(p.answer);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditQuestion("");
    setEditAnswer("");
  }

  async function handleSaveEdit(qaId: string) {
    if (!editQuestion.trim() || !editAnswer.trim()) return;
    setBusyId(qaId);
    try {
      await updateQAPair(qaId, editQuestion.trim(), editAnswer.trim());
      cancelEdit();
      await loadPairs();
      setError(null);
    } catch {
      setError("Failed to update Q&A pair.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(qaId: string) {
    setBusyId(qaId);
    try {
      await deleteQAPair(qaId);
      await loadPairs();
      setError(null);
    } catch {
      setError("Failed to delete Q&A pair.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-gray-50">
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-gray-900">Knowledge Base</h1>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto max-w-2xl">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-gray-900">Add a Q&A pair</h2>
          <div className="flex flex-col gap-3">
            <input
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
              placeholder="Question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={saving}
            />
            <textarea
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
              placeholder="Answer"
              rows={3}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              disabled={saving}
            />
            <button
              className="self-start rounded-full bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={handleAdd}
              disabled={saving || !question.trim() || !answer.trim()}
            >
              {saving ? "Adding…" : "Add"}
            </button>
          </div>
        </div>

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        <div className="mt-8">
          <h2 className="mb-3 text-sm font-semibold text-gray-900">
            Existing Q&A pairs {!loading && `(${pairs.length})`}
          </h2>

          {loading && <p className="text-sm text-gray-400">Loading…</p>}

          {!loading && pairs.length === 0 && (
            <p className="text-sm text-gray-400">No Q&A pairs yet.</p>
          )}

          <div className="flex flex-col gap-3">
            {pairs.map((p) => (
              <div
                key={p.qa_id}
                className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
              >
                {editingId === p.qa_id ? (
                  <div className="flex flex-col gap-2">
                    <input
                      className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
                      value={editQuestion}
                      onChange={(e) => setEditQuestion(e.target.value)}
                      disabled={busyId === p.qa_id}
                    />
                    <textarea
                      className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
                      rows={3}
                      value={editAnswer}
                      onChange={(e) => setEditAnswer(e.target.value)}
                      disabled={busyId === p.qa_id}
                    />
                    <div className="flex gap-2">
                      <button
                        className="rounded-full bg-blue-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                        onClick={() => handleSaveEdit(p.qa_id)}
                        disabled={busyId === p.qa_id || !editQuestion.trim() || !editAnswer.trim()}
                      >
                        Save
                      </button>
                      <button
                        className="rounded-full border border-gray-300 px-4 py-1.5 text-sm font-medium text-gray-700 disabled:opacity-50"
                        onClick={cancelEdit}
                        disabled={busyId === p.qa_id}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{p.question}</p>
                      <p className="mt-1 text-sm text-gray-600">{p.answer}</p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        className="text-sm font-medium text-blue-600 hover:underline disabled:opacity-50"
                        onClick={() => startEdit(p)}
                        disabled={busyId === p.qa_id}
                      >
                        Edit
                      </button>
                      <button
                        className="text-sm font-medium text-red-600 hover:underline disabled:opacity-50"
                        onClick={() => handleDelete(p.qa_id)}
                        disabled={busyId === p.qa_id}
                      >
                        {busyId === p.qa_id ? "…" : "Delete"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        </div>
      </main>
    </div>
  );
}
