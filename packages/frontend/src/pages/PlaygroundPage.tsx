import React, { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Film,
  Headphones,
  Image as ImageIcon,
  MessageSquare,
  Play,
  Search,
  Square,
  Trash2,
  Volume2,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Switch,
  Textarea,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch, formatBytes } from "../lib/api";

type TabKind = "chat" | "images" | "video" | "audio";

interface ModelItem {
  id: string;
}

interface VoiceItem {
  id: string;
  name: string;
  gender: string;
  accent: string;
  language: string;
  language_group: string;
  tone: string;
  description: string;
  long_description: string;
  cached: boolean;
  preview_url: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

interface RawResponseState {
  status: number;
  statusText: string;
  latencyMs: number;
  headers: Record<string, string>;
  body: string;
}

function CurlInspector({
  curlCmd,
  rawResponse,
  rawKey,
}: {
  curlCmd: string;
  rawResponse: RawResponseState | null;
  rawKey: string;
}) {
  const toast = useToast();
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);

  const displayCurl = useMemo(() => {
    if (!curlCmd) return "";
    if (showKey || !rawKey) return curlCmd;
    return curlCmd.split(rawKey).join("••••••••••••••••");
  }, [curlCmd, showKey, rawKey]);

  const handleCopy = () => {
    if (!curlCmd) return;
    navigator.clipboard.writeText(curlCmd);
    setCopied(true);
    toast.info("cURL command copied to clipboard.");
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="rounded-lg border border-zinc-800/80 bg-zinc-950/70 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3.5 py-2.5 text-left hover:bg-zinc-900/60 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 text-zinc-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-zinc-500" />
          )}
          <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
            cURL & Raw Response
          </span>
        </div>
        <div className="flex items-center gap-2">
          {rawResponse && (
            <Badge
              variant={
                rawResponse.status >= 200 && rawResponse.status < 300
                  ? "success"
                  : "danger"
              }
            >
              {rawResponse.status} {rawResponse.statusText} ·{" "}
              {rawResponse.latencyMs}ms
            </Badge>
          )}
        </div>
      </button>

      {open && (
        <div className="border-t border-zinc-800/80 bg-zinc-950 p-3.5 space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                cURL Command
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowKey((v) => !v)}
                  className="h-6 px-2 text-[11px]"
                >
                  {showKey ? (
                    <EyeOff className="h-3 w-3" />
                  ) : (
                    <Eye className="h-3 w-3" />
                  )}
                  {showKey ? "Hide Key" : "Show Key"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCopy}
                  className="h-6 px-2 text-[11px]"
                >
                  {copied ? (
                    <Check className="h-3 w-3 text-emerald-400" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
            <pre className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900/80 p-2.5 text-[11px] text-zinc-300 font-mono whitespace-pre-wrap">
              {displayCurl}
            </pre>
          </div>

          {rawResponse && (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                Response Body
              </div>
              <pre className="max-h-60 overflow-y-auto overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900/80 p-2.5 text-[11px] text-emerald-300/90 font-mono whitespace-pre-wrap">
                {rawResponse.body}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function PlaygroundPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState<TabKind>("chat");

  // Fetch API key for /v1/* client calls
  const { data: apiKeyData } = useQuery({
    queryKey: ["apikey"],
    queryFn: () => apiFetch<{ raw_key: string }>("/admin/apikey"),
  });
  const rawKey = apiKeyData?.raw_key || "";
  const baseUrl = `${window.location.origin}/v1`;

  // Fetch models list
  const { data: modelsData } = useQuery({
    queryKey: ["v1_models", rawKey],
    queryFn: () =>
      apiFetch<{ data: ModelItem[] }>("/v1/models", {
        headers: { Authorization: `Bearer ${rawKey}` },
      }),
    enabled: Boolean(rawKey),
  });

  const availableModels = modelsData?.data?.map((m) => m.id) || [
    "muse-spark",
    "muse-image",
    "muse-video",
    "muse-tts",
    "tts-1",
    "tts-1-hd",
    "gpt-4o-mini-tts",
  ];

  // -------------------------------------------------------------------------
  // TAB 1: CHAT STATE
  // -------------------------------------------------------------------------
  const [chatMode, setChatMode] = useState<"chat_completions" | "responses">(
    "chat_completions",
  );
  const [chatModel, setChatModel] = useState("muse-spark");
  const [chatStream, setChatStream] = useState(true);
  const [chatInstructions, setChatInstructions] = useState("");
  const [chatRefImageUrl, setChatRefImageUrl] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatStreaming, setChatStreaming] = useState(false);
  const [chatRawResp, setChatRawResp] = useState<RawResponseState | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);

  const chatCurl = useMemo(() => {
    const ep =
      chatMode === "chat_completions"
        ? `${baseUrl}/chat/completions`
        : `${baseUrl}/responses`;
    let bodyObj: any;
    if (chatMode === "chat_completions") {
      const msgs = [
        ...chatMessages.map((m) => ({ role: m.role, content: m.content })),
      ];
      if (chatInput.trim()) {
        msgs.push({ role: "user", content: chatInput.trim() });
      }
      bodyObj = { model: chatModel, messages: msgs, stream: chatStream };
    } else {
      bodyObj = {
        model: chatModel,
        instructions: chatInstructions || undefined,
        input: chatInput || "Hello",
        stream: chatStream,
      };
    }
    return `curl -X POST "${ep}" \\\n  -H "Authorization: Bearer ${rawKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(bodyObj, null, 2)}'`;
  }, [
    baseUrl,
    chatMode,
    chatModel,
    chatStream,
    chatInstructions,
    chatInput,
    chatMessages,
    rawKey,
  ]);

  const handleSendChat = async () => {
    if (!chatInput.trim() || !rawKey || chatStreaming) return;
    const userText = chatInput.trim();
    setChatInput("");

    let userContent: any = userText;
    if (chatRefImageUrl.trim()) {
      userContent = [
        { type: "text", text: userText },
        { type: "image_url", image_url: { url: chatRefImageUrl.trim() } },
      ];
    }

    const newMsgs: ChatMessage[] = [
      ...chatMessages,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: typeof userContent === "string" ? userContent : userText,
      },
    ];
    setChatMessages(newMsgs);

    const assistantMsgId = `asst_${Date.now()}`;
    setChatMessages((prev) => [
      ...prev,
      { id: assistantMsgId, role: "assistant", content: "" },
    ]);

    const abortCtrl = new AbortController();
    chatAbortRef.current = abortCtrl;
    setChatStreaming(true);
    const t0 = performance.now();

    try {
      const ep =
        chatMode === "chat_completions"
          ? `${baseUrl}/chat/completions`
          : `${baseUrl}/responses`;
      let payload: any;
      if (chatMode === "chat_completions") {
        const sendMsgs = [];
        if (chatInstructions.trim()) {
          sendMsgs.push({ role: "system", content: chatInstructions.trim() });
        }
        for (const m of newMsgs) {
          sendMsgs.push({ role: m.role, content: m.content });
        }
        payload = { model: chatModel, messages: sendMsgs, stream: chatStream };
      } else {
        payload = {
          model: chatModel,
          instructions: chatInstructions.trim() || undefined,
          input: userText,
          stream: chatStream,
        };
      }

      const res = await fetch(ep, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${rawKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: abortCtrl.signal,
      });

      const latencyMs = Math.round(performance.now() - t0);
      const respHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        respHeaders[k] = v;
      });

      if (!res.ok) {
        const errText = await res.text();
        setChatRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: errText,
        });
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: `Error: ${errText}` }
              : m,
          ),
        );
        return;
      }

      if (chatStream && res.body) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let accumulated = "";
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (
              !trimmed ||
              trimmed.startsWith(":") ||
              trimmed === "data: [DONE]"
            )
              continue;
            if (trimmed.startsWith("data: ")) {
              try {
                const parsed = JSON.parse(trimmed.slice(6));
                const delta = parsed.choices?.[0]?.delta?.content || "";
                if (delta) {
                  accumulated += delta;
                  setChatMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsgId
                        ? { ...m, content: accumulated }
                        : m,
                    ),
                  );
                }
              } catch {
                // partial json or response format
              }
            } else if (
              trimmed.startsWith("event: response.output_text.delta")
            ) {
              // responses API stream
            }
          }
        }

        setChatRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: accumulated || "(Stream ended)",
        });
      } else {
        const data = await res.json();
        const fullContent =
          data.choices?.[0]?.message?.content ||
          data.output?.[0]?.content?.[0]?.text ||
          JSON.stringify(data, null, 2);
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId ? { ...m, content: fullContent } : m,
          ),
        );
        setChatRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: JSON.stringify(data, null, 2),
        });
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        toast.error(`Chat error: ${err.message}`);
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: `Error: ${err.message}` }
              : m,
          ),
        );
      }
    } finally {
      setChatStreaming(false);
      chatAbortRef.current = null;
    }
  };

  const handleStopChat = () => {
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
      chatAbortRef.current = null;
    }
    setChatStreaming(false);
  };

  // -------------------------------------------------------------------------
  // TAB 2: IMAGES STATE
  // -------------------------------------------------------------------------
  const [imgMode, setImgMode] = useState<"generations" | "edits">(
    "generations",
  );
  const [imgPrompt, setImgPrompt] = useState("");
  const [imgSize, setImgSize] = useState("16:9");
  const [imgFormat, setImgFormat] = useState<"url" | "b64_json">("url");
  const [imgAsync, setImgAsync] = useState(false);
  const [imgRefUrl, setImgRefUrl] = useState("");
  const [imgLoading, setImgLoading] = useState(false);
  const [imgResultUrl, setImgResultUrl] = useState<string | null>(null);
  const [imgTaskProgress, setImgTaskProgress] = useState<number | null>(null);
  const [imgRawResp, setImgRawResp] = useState<RawResponseState | null>(null);

  const imgCurl = useMemo(() => {
    const ep =
      imgMode === "generations"
        ? `${baseUrl}/images/generations`
        : `${baseUrl}/images/edits`;
    const payload: any = {
      model: "muse-image",
      prompt: imgPrompt || "Neon cybernetic shiba inu",
      size: imgSize,
      response_format: imgFormat,
      async: imgAsync,
    };
    if (imgRefUrl) payload.image = imgRefUrl;
    return `curl -X POST "${ep}" \\\n  -H "Authorization: Bearer ${rawKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(payload, null, 2)}'`;
  }, [
    baseUrl,
    imgMode,
    imgPrompt,
    imgSize,
    imgFormat,
    imgAsync,
    imgRefUrl,
    rawKey,
  ]);

  const handleGenerateImage = async () => {
    if (!imgPrompt.trim() || !rawKey || imgLoading) return;
    setImgLoading(true);
    setImgResultUrl(null);
    setImgTaskProgress(null);
    const t0 = performance.now();

    try {
      const ep =
        imgMode === "generations"
          ? `${baseUrl}/images/generations`
          : `${baseUrl}/images/edits`;
      const payload: any = {
        model: "muse-image",
        prompt: imgPrompt.trim(),
        size: imgSize,
        response_format: imgFormat,
        async: imgAsync,
      };
      if (imgRefUrl.trim()) payload.image = imgRefUrl.trim();

      const res = await fetch(ep, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${rawKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const latencyMs = Math.round(performance.now() - t0);
      const respHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        respHeaders[k] = v;
      });

      const data = await res.json();
      setImgRawResp({
        status: res.status,
        statusText: res.statusText,
        latencyMs,
        headers: respHeaders,
        body: JSON.stringify(data, null, 2),
      });

      if (!res.ok) {
        throw new Error(
          data?.detail?.error?.message ||
            data?.detail ||
            "Image generation failed",
        );
      }

      if (imgAsync && data.id) {
        // Poll async task
        const taskId = data.id;
        setImgTaskProgress(data.progress || 10);
        let completed = false;
        while (!completed) {
          await new Promise((r) => setTimeout(r, 2000));
          const pollRes = await fetch(`${baseUrl}/images/tasks/${taskId}`, {
            headers: { Authorization: `Bearer ${rawKey}` },
          });
          const pollData = await pollRes.json();
          setImgTaskProgress(pollData.progress || 50);
          if (pollData.status === "completed") {
            completed = true;
            setImgResultUrl(pollData.url);
          } else if (pollData.status === "failed") {
            throw new Error(pollData.error || "Async task failed");
          }
        }
      } else if (data.data?.[0]?.url) {
        setImgResultUrl(data.data[0].url);
      } else if (data.data?.[0]?.b64_json) {
        setImgResultUrl(`data:image/webp;base64,${data.data[0].b64_json}`);
      }
      toast.success("Image generated successfully!");
    } catch (err: any) {
      toast.error(`Image error: ${err.message}`);
    } finally {
      setImgLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // TAB 3: VIDEO STATE
  // -------------------------------------------------------------------------
  const [vidPrompt, setVidPrompt] = useState("");
  const [vidDuration, setVidDuration] = useState("5");
  const [vidSize, setVidSize] = useState("16:9");
  const [vidRefUrl, setVidRefUrl] = useState("");
  const [vidLoading, setVidLoading] = useState(false);
  const [vidTaskId, setVidTaskId] = useState<string | null>(null);
  const [vidStatus, setVidStatus] = useState<string | null>(null);
  const [vidProgress, setVidProgress] = useState(0);
  const [vidResultUrl, setVidResultUrl] = useState<string | null>(null);
  const [vidRawResp, setVidRawResp] = useState<RawResponseState | null>(null);

  const vidCurl = useMemo(() => {
    const payload: any = {
      model: "muse-video",
      prompt: vidPrompt || "Golden maple leaves drifting in autumn breeze",
      duration: parseInt(vidDuration, 10),
      size: vidSize,
    };
    if (vidRefUrl) payload.image = vidRefUrl;
    return `curl -X POST "${baseUrl}/videos" \\\n  -H "Authorization: Bearer ${rawKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(payload, null, 2)}'`;
  }, [baseUrl, vidPrompt, vidDuration, vidSize, vidRefUrl, rawKey]);

  const handleGenerateVideo = async () => {
    if (!vidPrompt.trim() || !rawKey || vidLoading) return;
    setVidLoading(true);
    setVidResultUrl(null);
    setVidTaskId(null);
    setVidProgress(5);
    setVidStatus("queued");
    const t0 = performance.now();

    try {
      const payload: any = {
        model: "muse-video",
        prompt: vidPrompt.trim(),
        duration: parseInt(vidDuration, 10),
        size: vidSize,
      };
      if (vidRefUrl.trim()) payload.image = vidRefUrl.trim();

      const res = await fetch(`${baseUrl}/videos`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${rawKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const latencyMs = Math.round(performance.now() - t0);
      const respHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        respHeaders[k] = v;
      });

      const data = await res.json();
      setVidRawResp({
        status: res.status,
        statusText: res.statusText,
        latencyMs,
        headers: respHeaders,
        body: JSON.stringify(data, null, 2),
      });

      if (!res.ok) {
        throw new Error(
          data?.detail?.error?.message ||
            data?.detail ||
            "Video creation failed",
        );
      }

      const taskId = data.id;
      setVidTaskId(taskId);

      // Poll video progress
      let completed = false;
      while (!completed) {
        await new Promise((r) => setTimeout(r, 2000));
        const pollRes = await fetch(`${baseUrl}/videos/${taskId}`, {
          headers: { Authorization: `Bearer ${rawKey}` },
        });
        const pollData = await pollRes.json();
        setVidStatus(pollData.status || "processing");
        setVidProgress(pollData.progress || 20);

        if (pollData.status === "completed") {
          completed = true;
          setVidResultUrl(pollData.url);
          setVidProgress(100);
        } else if (pollData.status === "failed") {
          throw new Error(pollData.error || "Video generation failed");
        }
      }
      toast.success("Video generated successfully!");
    } catch (err: any) {
      toast.error(`Video error: ${err.message}`);
      setVidStatus("failed");
    } finally {
      setVidLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // TAB 4: AUDIO & VOICES STATE
  // -------------------------------------------------------------------------
  const [voiceSearch, setVoiceSearch] = useState("");
  const [voiceLangGroup, setVoiceLangGroup] = useState("");
  const [voiceGender, setVoiceGender] = useState("");
  const [voicePage, setVoicePage] = useState(1);
  const pageSize = 10;

  // Selected voice for Speech Tester
  const [selectedVoiceId, setSelectedVoiceId] = useState("avocado_v2:MAI_01");
  const [speechModel, setSpeechModel] = useState("muse-tts");
  const [speechSpeed, setSpeechSpeed] = useState("1.0");
  const [speechFormat, setSpeechFormat] = useState<"mp3" | "url">("mp3");
  const [speechInstructions, setSpeechInstructions] = useState("");
  const [speechInput, setSpeechInput] = useState(
    "Hello world! [laughs] That is fantastic.",
  );
  const [speechLoading, setSpeechLoading] = useState(false);
  const [speechAudioUrl, setSpeechAudioUrl] = useState<string | null>(null);
  const [speechRawResp, setSpeechRawResp] = useState<RawResponseState | null>(
    null,
  );

  // Playing preview tracking
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  // Fetch voice catalog
  const { data: voicesResp } = useQuery({
    queryKey: ["audio_voices", rawKey],
    queryFn: () =>
      apiFetch<{ total: number; data: VoiceItem[] }>("/v1/audio/voices", {
        headers: { Authorization: `Bearer ${rawKey}` },
      }),
    enabled: Boolean(rawKey),
  });

  const allVoices = voicesResp?.data || [];

  // Auto-select valid voice if current selected voice is not in catalog
  React.useEffect(() => {
    if (allVoices.length > 0) {
      const exists = allVoices.some(
        (v) =>
          v.id === selectedVoiceId ||
          v.name.toLowerCase() === selectedVoiceId.toLowerCase(),
      );
      if (!exists) {
        setSelectedVoiceId(allVoices[0].id);
      }
    }
  }, [allVoices, selectedVoiceId]);

  const selectedVoiceObj = useMemo(() => {
    return allVoices.find(
      (v) =>
        v.id === selectedVoiceId ||
        v.name.toLowerCase() === selectedVoiceId.toLowerCase(),
    );
  }, [allVoices, selectedVoiceId]);

  // Extract unique language groups
  const availableLangGroups = useMemo(() => {
    const s = new Set<string>();
    for (const v of allVoices) {
      if (v.language_group) s.add(v.language_group);
    }
    return Array.from(s).sort();
  }, [allVoices]);

  // Filter voices
  const filteredVoices = useMemo(() => {
    return allVoices.filter((v) => {
      if (voiceGender && v.gender !== voiceGender) return false;
      if (voiceLangGroup && v.language_group !== voiceLangGroup) return false;
      if (voiceSearch.trim()) {
        const q = voiceSearch.toLowerCase();
        const haystack =
          `${v.name} ${v.id} ${v.language_group} ${v.accent} ${v.tone} ${v.description} ${v.long_description || ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [allVoices, voiceGender, voiceLangGroup, voiceSearch]);

  const totalPages = Math.max(1, Math.ceil(filteredVoices.length / pageSize));
  const pageVoices = useMemo(() => {
    const start = (voicePage - 1) * pageSize;
    return filteredVoices.slice(start, start + pageSize);
  }, [filteredVoices, voicePage]);

  const getVoiceRowKey = (voice: VoiceItem) =>
    `${voice.id}::${voice.language_group || voice.accent}`;

  // Play voice preview handler
  const handlePlayPreview = async (voice: VoiceItem) => {
    const rowKey = getVoiceRowKey(voice);
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
    }
    if (playingVoiceId === rowKey) {
      setPlayingVoiceId(null);
      return;
    }

    setPreviewLoadingId(rowKey);
    try {
      const langParam = voice.language_group
        ? `?language=${encodeURIComponent(voice.language_group)}`
        : "";
      const url = `${baseUrl}/audio/voices/${encodeURIComponent(voice.id)}/preview${langParam}`;
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${rawKey}` },
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(
          errJson?.detail?.error?.message ||
            errJson?.detail ||
            "Preview failed",
        );
      }
      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      previewAudioRef.current = audio;
      setPlayingVoiceId(rowKey);

      audio.onended = () => {
        setPlayingVoiceId(null);
      };
      await audio.play();
    } catch (err: any) {
      toast.error(`Preview error: ${err.message}`);
      setPlayingVoiceId(null);
    } finally {
      setPreviewLoadingId(null);
    }
  };

  // Speech generation handler
  const speechCurl = useMemo(() => {
    const payload = {
      model: speechModel,
      input: speechInput,
      voice: selectedVoiceId,
      instructions: speechInstructions || undefined,
      speed: parseFloat(speechSpeed) || 1.0,
      response_format: speechFormat,
    };
    return `curl -X POST "${baseUrl}/audio/speech" \\\n  -H "Authorization: Bearer ${rawKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(payload, null, 2)}'`;
  }, [
    baseUrl,
    speechModel,
    speechInput,
    selectedVoiceId,
    speechInstructions,
    speechSpeed,
    speechFormat,
    rawKey,
  ]);

  const handleGenerateSpeech = async () => {
    if (!speechInput.trim() || !rawKey || speechLoading) return;
    setSpeechLoading(true);
    setSpeechAudioUrl(null);
    const t0 = performance.now();

    try {
      const payload = {
        model: speechModel,
        input: speechInput.trim(),
        voice: selectedVoiceId,
        instructions: speechInstructions.trim() || undefined,
        speed: parseFloat(speechSpeed) || 1.0,
        response_format: speechFormat,
      };

      const res = await fetch(`${baseUrl}/audio/speech`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${rawKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const latencyMs = Math.round(performance.now() - t0);
      const respHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        respHeaders[k] = v;
      });

      if (!res.ok) {
        const errJson = await res.json();
        setSpeechRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: JSON.stringify(errJson, null, 2),
        });
        throw new Error(
          errJson?.detail?.error?.message ||
            errJson?.detail ||
            "Speech generation failed",
        );
      }

      if (speechFormat === "mp3") {
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        setSpeechAudioUrl(blobUrl);
        setSpeechRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: `Binary audio/mpeg (${formatBytes(blob.size)})`,
        });
      } else {
        const data = await res.json();
        setSpeechRawResp({
          status: res.status,
          statusText: res.statusText,
          latencyMs,
          headers: respHeaders,
          body: JSON.stringify(data, null, 2),
        });
        if (data.data?.[0]?.url) {
          setSpeechAudioUrl(data.data[0].url);
        }
      }
      toast.success("Speech audio generated successfully!");
    } catch (err: any) {
      toast.error(`Speech error: ${err.message}`);
    } finally {
      setSpeechLoading(false);
    }
  };

  const insertEmotionCue = (cue: string) => {
    setSpeechInput((prev) => `${prev} ${cue} `);
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            API Playground
          </h1>
          <p className="text-sm text-zinc-400">
            Live interactive playground for testing{" "}
            <code className="text-zinc-300 font-mono">/v1/*</code> endpoints
            with preview voice cache.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center rounded-lg border border-zinc-800 bg-zinc-950 p-1">
          <button
            type="button"
            onClick={() => setActiveTab("chat")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              activeTab === "chat"
                ? "bg-zinc-800 text-white"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Chat
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("images")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              activeTab === "images"
                ? "bg-zinc-800 text-white"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <ImageIcon className="h-3.5 w-3.5" />
            Images
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("video")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              activeTab === "video"
                ? "bg-zinc-800 text-white"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Film className="h-3.5 w-3.5" />
            Video
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("audio")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              activeTab === "audio"
                ? "bg-zinc-800 text-white"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Headphones className="h-3.5 w-3.5" />
            Audio & Voices
          </button>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* TAB 1: CHAT */}
      {/* ===================================================================== */}
      {activeTab === "chat" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Controls Column */}
          <div className="space-y-4 lg:col-span-5 xl:col-span-4">
            <Card>
              <CardHeader>
                <CardTitle>Chat Configuration</CardTitle>
                <CardDescription>Select API mode and model</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    API Endpoint
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 rounded-lg border border-zinc-800 bg-zinc-950 p-1 text-xs">
                    <button
                      type="button"
                      onClick={() => setChatMode("chat_completions")}
                      className={`rounded px-2 py-1.5 text-center font-medium transition-colors cursor-pointer text-ellipsis overflow-hidden whitespace-nowrap ${
                        chatMode === "chat_completions"
                          ? "bg-zinc-800 text-white"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Chat Completions
                    </button>
                    <button
                      type="button"
                      onClick={() => setChatMode("responses")}
                      className={`rounded px-2 py-1.5 text-center font-medium transition-colors cursor-pointer whitespace-nowrap ${
                        chatMode === "responses"
                          ? "bg-zinc-800 text-white"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Responses
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Model
                  </label>
                  <select
                    value={chatModel}
                    onChange={(e) => setChatModel(e.target.value)}
                    className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    {availableModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-zinc-300">
                    Stream Response (SSE)
                  </span>
                  <Switch
                    checked={chatStream}
                    onCheckedChange={setChatStream}
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    System / Instructions (Optional)
                  </label>
                  <Textarea
                    rows={3}
                    placeholder="e.g. You are a helpful AI assistant..."
                    value={chatInstructions}
                    onChange={(e) => setChatInstructions(e.target.value)}
                    className="text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Reference Image URL (Optional)
                  </label>
                  <Input
                    placeholder="https://... image link"
                    value={chatRefImageUrl}
                    onChange={(e) => setChatRefImageUrl(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => {
                    setChatMessages([]);
                    setChatRawResp(null);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5 text-zinc-400" />
                  Clear Conversation
                </Button>
              </CardContent>
            </Card>

            <CurlInspector
              curlCmd={chatCurl}
              rawResponse={chatRawResp}
              rawKey={rawKey}
            />
          </div>

          {/* Conversation Column */}
          <div className="space-y-4 lg:col-span-7 xl:col-span-8">
            <Card className="flex flex-col h-[600px]">
              <CardHeader className="border-b border-zinc-800/80 pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle>Conversation Stream</CardTitle>
                  <Badge variant="default">{chatModel}</Badge>
                </div>
              </CardHeader>

              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {chatMessages.length === 0 ? (
                  <div className="flex h-full flex-col items-center justify-center text-center text-zinc-500">
                    <MessageSquare className="h-8 w-8 mb-2 opacity-40" />
                    <p className="text-sm">No messages yet.</p>
                    <p className="text-xs text-zinc-600">
                      Type a message below to test chat completions.
                    </p>
                  </div>
                ) : (
                  chatMessages.map((m) => (
                    <div
                      key={m.id}
                      className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}
                    >
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                        {m.role}
                      </div>
                      <div
                        className={`max-w-[85%] rounded-lg px-3.5 py-2.5 text-sm whitespace-pre-wrap ${
                          m.role === "user"
                            ? "bg-blue-600/90 text-white"
                            : "bg-zinc-800/90 text-zinc-200 border border-zinc-700/60"
                        }`}
                      >
                        {m.content ||
                          (chatStreaming ? (
                            <span className="animate-pulse">Thinking...</span>
                          ) : (
                            ""
                          ))}
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className="border-t border-zinc-800/80 p-3 bg-zinc-950/60 flex items-center gap-2">
                <Textarea
                  rows={2}
                  placeholder="Type message (Press Enter to send, Shift+Enter for newline)..."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendChat();
                    }
                  }}
                  className="flex-1 text-xs"
                />
                <div className="flex flex-col gap-1">
                  {chatStreaming ? (
                    <Button variant="danger" onClick={handleStopChat}>
                      <Square className="h-4 w-4" />
                      Stop
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      onClick={handleSendChat}
                      disabled={!chatInput.trim()}
                    >
                      Send
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 2: IMAGES */}
      {/* ===================================================================== */}
      {activeTab === "images" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-5 xl:col-span-5 2xl:col-span-4">
            <Card>
              <CardHeader>
                <CardTitle>Image Parameters</CardTitle>
                <CardDescription>Generations & Edits</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Mode
                  </label>
                  <div className="grid grid-cols-2 gap-1 rounded-lg border border-zinc-800 bg-zinc-950 p-1 text-xs">
                    <button
                      type="button"
                      onClick={() => setImgMode("generations")}
                      className={`rounded px-2 py-1 text-center font-medium transition-colors cursor-pointer ${
                        imgMode === "generations"
                          ? "bg-zinc-800 text-white"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Generations
                    </button>
                    <button
                      type="button"
                      onClick={() => setImgMode("edits")}
                      className={`rounded px-2 py-1 text-center font-medium transition-colors cursor-pointer ${
                        imgMode === "edits"
                          ? "bg-zinc-800 text-white"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Edits
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Prompt
                  </label>
                  <Textarea
                    rows={4}
                    placeholder="A neon shiba inu in rainy Tokyo cyberpunk street..."
                    value={imgPrompt}
                    onChange={(e) => setImgPrompt(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Aspect Ratio / Size
                  </label>
                  <select
                    value={imgSize}
                    onChange={(e) => setImgSize(e.target.value)}
                    className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="16:9">16:9 (Landscape)</option>
                    <option value="9:16">9:16 (Portrait / Reel)</option>
                    <option value="1:1">1:1 (Square)</option>
                    <option value="4:3">4:3 (Classic)</option>
                    <option value="3:4">3:4 (Portrait)</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Response Format
                  </label>
                  <select
                    value={imgFormat}
                    onChange={(e) => setImgFormat(e.target.value as any)}
                    className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="url">URL</option>
                    <option value="b64_json">b64_json (Base64)</option>
                  </select>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-xs font-medium text-zinc-300">
                      Async Task Mode
                    </span>
                    <p className="text-[11px] text-zinc-500">
                      Return task ID & poll status
                    </p>
                  </div>
                  <Switch checked={imgAsync} onCheckedChange={setImgAsync} />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Reference Image URL{" "}
                    {imgMode === "edits" && (
                      <span className="text-rose-400">*</span>
                    )}
                  </label>
                  <Input
                    placeholder="https://... or data:image/png;base64,..."
                    value={imgRefUrl}
                    onChange={(e) => setImgRefUrl(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <Button
                  variant="primary"
                  className="w-full"
                  loading={imgLoading}
                  onClick={handleGenerateImage}
                  disabled={
                    !imgPrompt.trim() ||
                    (imgMode === "edits" && !imgRefUrl.trim())
                  }
                >
                  Generate Image
                </Button>
              </CardContent>
            </Card>

            <CurlInspector
              curlCmd={imgCurl}
              rawResponse={imgRawResp}
              rawKey={rawKey}
            />
          </div>

          <div className="space-y-4 lg:col-span-7 xl:col-span-7 2xl:col-span-8">
            <Card className="min-h-[500px] flex flex-col justify-center items-center p-6">
              {imgLoading ? (
                <div className="flex flex-col items-center justify-center text-center space-y-3">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
                  <p className="text-sm text-zinc-300">
                    Generating image via WSS pool...
                  </p>
                  {imgTaskProgress !== null && (
                    <div className="w-64 rounded-full bg-zinc-800 h-2 overflow-hidden">
                      <div
                        className="bg-blue-500 h-full transition-all duration-300"
                        style={{ width: `${imgTaskProgress}%` }}
                      />
                    </div>
                  )}
                </div>
              ) : imgResultUrl ? (
                <div className="w-full flex flex-col items-center space-y-4">
                  <div className="flex items-center justify-between w-full">
                    <Badge variant="success">Completed · {imgSize}</Badge>
                    <div className="flex items-center gap-2">
                      <a href={imgResultUrl} target="_blank" rel="noreferrer">
                        <Button variant="outline" size="sm">
                          <ExternalLink className="h-3.5 w-3.5" />
                          Open URL
                        </Button>
                      </a>
                      <a href={imgResultUrl} download="generated.webp">
                        <Button variant="outline" size="sm">
                          <Download className="h-3.5 w-3.5" />
                          Download
                        </Button>
                      </a>
                    </div>
                  </div>
                  <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 max-h-[520px]">
                    <img
                      src={imgResultUrl}
                      alt="Generated"
                      className="object-contain max-h-[520px] max-w-full"
                    />
                  </div>
                </div>
              ) : (
                <div className="text-center text-zinc-500 space-y-2">
                  <ImageIcon className="h-10 w-10 mx-auto opacity-40" />
                  <p className="text-sm">No image generated yet.</p>
                  <p className="text-xs text-zinc-600">
                    Enter a prompt and click Generate Image.
                  </p>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 3: VIDEO */}
      {/* ===================================================================== */}
      {activeTab === "video" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-5 xl:col-span-5 2xl:col-span-4">
            <Card>
              <CardHeader>
                <CardTitle>Video Parameters</CardTitle>
                <CardDescription>Text & Image-to-Video</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Prompt
                  </label>
                  <Textarea
                    rows={4}
                    placeholder="Golden maple leaves drifting gently in autumn wind..."
                    value={vidPrompt}
                    onChange={(e) => setVidPrompt(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Duration (seconds)
                  </label>
                  <select
                    value={vidDuration}
                    onChange={(e) => setVidDuration(e.target.value)}
                    className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="5">5 seconds</option>
                    <option value="8">8 seconds</option>
                    <option value="10">10 seconds</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Aspect Ratio / Size
                  </label>
                  <select
                    value={vidSize}
                    onChange={(e) => setVidSize(e.target.value)}
                    className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="16:9">16:9 (Landscape)</option>
                    <option value="9:16">9:16 (Reel / Shorts)</option>
                    <option value="1:1">1:1 (Square)</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    First-Frame Image URL (Optional)
                  </label>
                  <Input
                    placeholder="https://... for image-to-video"
                    value={vidRefUrl}
                    onChange={(e) => setVidRefUrl(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <Button
                  variant="primary"
                  className="w-full"
                  loading={vidLoading}
                  onClick={handleGenerateVideo}
                  disabled={!vidPrompt.trim()}
                >
                  Generate Video
                </Button>
              </CardContent>
            </Card>

            <CurlInspector
              curlCmd={vidCurl}
              rawResponse={vidRawResp}
              rawKey={rawKey}
            />
          </div>

          <div className="space-y-4 lg:col-span-7 xl:col-span-7 2xl:col-span-8">
            <Card className="min-h-[500px] flex flex-col justify-center items-center p-6">
              {vidLoading ? (
                <div className="flex flex-col items-center justify-center text-center space-y-3">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
                  <p className="text-sm font-medium text-zinc-200">
                    Generating video {vidTaskId ? `(${vidTaskId})` : ""}...
                  </p>
                  <p className="text-xs text-zinc-400 capitalize">
                    Status: {vidStatus} ({vidProgress}%)
                  </p>
                  <div className="w-72 rounded-full bg-zinc-800 h-2.5 overflow-hidden">
                    <div
                      className="bg-blue-500 h-full transition-all duration-500"
                      style={{ width: `${vidProgress}%` }}
                    />
                  </div>
                </div>
              ) : vidResultUrl ? (
                <div className="w-full flex flex-col items-center space-y-4">
                  <div className="flex items-center justify-between w-full">
                    <Badge variant="success">
                      Completed · {vidSize} · {vidDuration}s
                    </Badge>
                    <a href={vidResultUrl} download="video.mp4">
                      <Button variant="outline" size="sm">
                        <Download className="h-3.5 w-3.5" />
                        Download MP4
                      </Button>
                    </a>
                  </div>
                  <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 w-full max-w-2xl">
                    <video
                      src={vidResultUrl}
                      controls
                      className="w-full h-auto rounded-xl"
                      autoPlay
                      loop
                    />
                  </div>
                </div>
              ) : (
                <div className="text-center text-zinc-500 space-y-2">
                  <Film className="h-10 w-10 mx-auto opacity-40" />
                  <p className="text-sm">No video generated yet.</p>
                  <p className="text-xs text-zinc-600">
                    Enter a prompt and click Generate Video.
                  </p>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 4: AUDIO & VOICES */}
      {/* ===================================================================== */}
      {activeTab === "audio" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left: Voice Catalog */}
          <div className="space-y-4 lg:col-span-7 xl:col-span-7">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Voice Catalog</CardTitle>
                    <CardDescription>
                      Listen to sample audio previews and select a voice for
                      speech generation.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Filters */}
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div className="relative sm:col-span-1">
                    <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
                    <Input
                      placeholder="Search name, tone..."
                      value={voiceSearch}
                      onChange={(e) => {
                        setVoiceSearch(e.target.value);
                        setVoicePage(1);
                      }}
                      className="pl-8 text-xs"
                    />
                  </div>
                  <select
                    value={voiceLangGroup}
                    onChange={(e) => {
                      setVoiceLangGroup(e.target.value);
                      setVoicePage(1);
                    }}
                    className="rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">
                      All Languages ({availableLangGroups.length})
                    </option>
                    {availableLangGroups.map((g) => (
                      <option key={g} value={g}>
                        {g}
                      </option>
                    ))}
                  </select>
                  <select
                    value={voiceGender}
                    onChange={(e) => {
                      setVoiceGender(e.target.value);
                      setVoicePage(1);
                    }}
                    className="rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">All Genders</option>
                    <option value="F">Female (F)</option>
                    <option value="M">Male (M)</option>
                  </select>
                </div>

                {/* Voice Table */}
                <div className="rounded-lg border border-zinc-800/80 overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-zinc-800/80 bg-zinc-950/80 text-zinc-400 font-medium">
                      <tr>
                        <th className="py-2.5 px-3">Voice</th>
                        <th className="py-2.5 px-3">Group / Accent</th>
                        <th className="py-2.5 px-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60 bg-zinc-950/40">
                      {pageVoices.length === 0 ? (
                        <tr>
                          <td
                            colSpan={3}
                            className="py-6 text-center text-zinc-500"
                          >
                            No voices found matching criteria.
                          </td>
                        </tr>
                      ) : (
                        pageVoices.map((v) => {
                          const rowKey = getVoiceRowKey(v);
                          const isPlaying = playingVoiceId === rowKey;
                          const isLoading = previewLoadingId === rowKey;
                          return (
                            <tr
                              key={rowKey}
                              className="hover:bg-zinc-900/50 transition-colors"
                            >
                              <td className="py-2.5 px-3">
                                <div
                                  className="font-semibold text-zinc-200"
                                  title={v.long_description || v.description}
                                >
                                  {v.name}
                                </div>
                                <div className="text-[10px] font-mono text-zinc-500">
                                  {v.id}
                                </div>
                                {v.long_description && (
                                  <div
                                    className="text-[11px] text-zinc-400 italic mt-0.5 line-clamp-1 max-w-[220px]"
                                    title={v.long_description}
                                  >
                                    {v.long_description}
                                  </div>
                                )}
                              </td>
                              <td className="py-2.5 px-3">
                                <div className="text-zinc-300">
                                  {v.language_group}
                                </div>
                                <div className="text-[10px] text-zinc-500">
                                  {v.gender} · {v.accent} · {v.tone}
                                </div>
                              </td>
                              <td className="py-2.5 px-3 text-right whitespace-nowrap space-x-1.5">
                                <Button
                                  variant={isPlaying ? "danger" : "outline"}
                                  size="sm"
                                  loading={isLoading}
                                  onClick={() => handlePlayPreview(v)}
                                  className="h-7 px-2.5 text-xs"
                                >
                                  {isPlaying ? (
                                    <>
                                      <Square className="h-3 w-3" />
                                    </>
                                  ) : (
                                    <>
                                      <Play className="h-3 w-3" />
                                    </>
                                  )}
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => {
                                    setSelectedVoiceId(v.id);
                                    toast.info(`Selected voice: ${v.name}`);
                                  }}
                                  className="h-7 px-2 text-xs text-blue-400 hover:text-blue-300"
                                >
                                  Use
                                </Button>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="flex items-center justify-between text-xs text-zinc-400 pt-1">
                  <span>
                    Showing {pageVoices.length} of {filteredVoices.length}{" "}
                    voices
                  </span>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={voicePage <= 1}
                      onClick={() => setVoicePage((p) => Math.max(1, p - 1))}
                      className="h-6 px-2 text-[11px]"
                    >
                      Prev
                    </Button>
                    <span className="px-2 font-mono text-[11px]">
                      {voicePage} / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={voicePage >= totalPages}
                      onClick={() =>
                        setVoicePage((p) => Math.min(totalPages, p + 1))
                      }
                      className="h-6 px-2 text-[11px]"
                    >
                      Next
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right: Test POST /v1/audio/speech */}
          <div className="space-y-4 lg:col-span-5 xl:col-span-5">
            <Card>
              <CardHeader>
                <CardTitle>Test Speech API (`/v1/audio/speech`)</CardTitle>
                <CardDescription>
                  Synthesize custom speech with style & emotion cues
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">
                      Selected Voice
                    </label>
                    <Input
                      value={selectedVoiceId}
                      onChange={(e) => setSelectedVoiceId(e.target.value)}
                      placeholder="e.g. avocado_v2:vdc_NOID25"
                      className="font-mono text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">
                      Model
                    </label>
                    <select
                      value={speechModel}
                      onChange={(e) => setSpeechModel(e.target.value)}
                      className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                    >
                      <option value="muse-tts">muse-tts (Default)</option>
                      <option value="tts-1">tts-1</option>
                      <option value="tts-1-hd">tts-1-hd</option>
                      <option value="gpt-4o-mini-tts">gpt-4o-mini-tts</option>
                    </select>
                  </div>
                </div>

                {selectedVoiceObj && (
                  <div className="rounded-md border border-zinc-800/80 bg-zinc-950/60 p-2.5 text-xs text-zinc-400 space-y-1">
                    <div className="flex items-center justify-between text-zinc-300 font-medium">
                      <span>
                        {selectedVoiceObj.name} ({selectedVoiceObj.language_group})
                      </span>
                      <span className="text-[10px] font-mono text-zinc-500">
                        {selectedVoiceObj.id}
                      </span>
                    </div>
                    {selectedVoiceObj.long_description && (
                      <div className="text-[11px] text-zinc-400 italic leading-relaxed">
                        {selectedVoiceObj.long_description}
                      </div>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">
                      Speed (0.25 - 4.0)
                    </label>
                    <Input
                      type="number"
                      step="0.1"
                      min="0.25"
                      max="4.0"
                      value={speechSpeed}
                      onChange={(e) => setSpeechSpeed(e.target.value)}
                      className="text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">
                      Response Format
                    </label>
                    <select
                      value={speechFormat}
                      onChange={(e) => setSpeechFormat(e.target.value as any)}
                      className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
                    >
                      <option value="mp3">mp3 (Binary Stream)</option>
                      <option value="url">url (JSON format)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-zinc-300">
                    Style Instructions (Optional)
                  </label>
                  <Input
                    placeholder="e.g. Speak warmly, conversational tone"
                    value={speechInstructions}
                    onChange={(e) => setSpeechInstructions(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <label className="text-xs font-medium text-zinc-300">
                      Input Text
                    </label>
                    <span className="text-[10px] text-zinc-500">
                      {speechInput.length} / 4096
                    </span>
                  </div>
                  <Textarea
                    rows={4}
                    value={speechInput}
                    onChange={(e) => setSpeechInput(e.target.value)}
                    placeholder="Enter text to speak..."
                    className="text-xs"
                  />
                </div>

                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Quick Emotion Cues
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      "[laughs]",
                      "[chuckles]",
                      "[giggles]",
                      "[sighs]",
                      "[gasps]",
                      "[coughs]",
                      "[sneezes]",
                      "[clears throat]",
                      "[pause]",
                      "[long pause]",
                      "[whispers]",
                      "[shouts]",
                      "[happy]",
                      "[excited]",
                      "[sad]",
                      "[angry]",
                    ].map((cue) => (
                      <button
                        key={cue}
                        type="button"
                        onClick={() => insertEmotionCue(cue)}
                        className="rounded border border-zinc-800 bg-zinc-900/80 px-2 py-0.5 text-[11px] font-mono text-zinc-300 hover:border-zinc-700 hover:bg-zinc-800 transition-colors cursor-pointer"
                      >
                        {cue}
                      </button>
                    ))}
                  </div>
                </div>

                <Button
                  variant="primary"
                  className="w-full"
                  loading={speechLoading}
                  onClick={handleGenerateSpeech}
                  disabled={!speechInput.trim()}
                >
                  <Volume2 className="h-4 w-4" />
                  Generate Speech
                </Button>

                {speechAudioUrl && (
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-emerald-400">
                        Audio Ready
                      </span>
                      <a href={speechAudioUrl} download="speech.mp3">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-[11px]"
                        >
                          <Download className="h-3 w-3" />
                          Download MP3
                        </Button>
                      </a>
                    </div>
                    <audio
                      src={speechAudioUrl}
                      controls
                      className="w-full h-8"
                      autoPlay
                    />
                  </div>
                )}
              </CardContent>
            </Card>

            <CurlInspector
              curlCmd={speechCurl}
              rawResponse={speechRawResp}
              rawKey={rawKey}
            />
          </div>
        </div>
      )}
    </div>
  );
}
