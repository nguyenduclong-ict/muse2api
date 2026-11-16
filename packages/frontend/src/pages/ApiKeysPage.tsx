import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Copy, Eye, EyeOff, RefreshCw } from "lucide-react";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch } from "../lib/api";

interface EndpointDoc {
  ep: string;
  mode: string;
  inputDoc: string;
  outputDoc: string;
}

const ENDPOINTS: EndpointDoc[] = [
  {
    ep: "POST /v1/chat/completions",
    mode: "SSE, Multimodal & Sync",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>, Content-Type: application/json
Body:
{
  "model": "muse-spark",
  "messages": [
    {"role": "user", "content": [
      {"type": "text", "text": "Describe this image"},
      {"type": "image_url", "image_url": {"url": "https://example.com/pic.png"}}
    ]}
  ],
  "stream": true
}`,
    outputDoc: `// stream=false:
{ "id": "chatcmpl-...", "object": "chat.completion", "choices": [{ "message": { "role": "assistant", "content": "..." } }] }
// stream=true:
data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"..."}}]}
data: [DONE]`,
  },
  {
    ep: "POST /v1/responses",
    mode: "SSE & Sync",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>, Content-Type: application/json
Body:
{
  "model": "muse-spark",
  "instructions": "Be concise",
  "input": "Write a haiku",
  "stream": true
}`,
    outputDoc: `// stream=true:
event: response.created
event: response.output_text.delta
event: response.completed
// stream=false:
{ "id": "resp_...", "object": "response", "output": [{ "type": "message", "content": [{ "type": "output_text", "text": "..." }] }] }`,
  },
  {
    ep: "POST /v1/images/generations",
    mode: "Sync, Async & Refs",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>, Content-Type: application/json
Body:
{
  "model": "muse-image",
  "prompt": "A neon shiba inu",
  "size": "16:9",
  "response_format": "url", // or "b64_json"
  "async": false
}
// Optional ref fields: image, images, reference_image`,
    outputDoc: `// async=false:
{ "created": 1794857411, "data": [{ "url": "http://.../v1/media/ima_xxx.webp", "size": "16:9", "kind": "image", "bytes": 123698 }] }
// async=true:
{ "id": "img_xxx", "status": "queued", "progress": 10 } -> poll GET /v1/images/tasks/{id}`,
  },
  {
    ep: "POST /v1/images/edits",
    mode: "Multipart & JSON",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>
1) multipart/form-data:
   - prompt: "Make the sky purple"
   - image (or image[] / file / video / audio): <file>
   - size / aspect_ratio, response_format, async
2) application/json:
   { "prompt": "...", "image": "https://... or data:image/png;base64,..." }`,
    outputDoc: `{ "created": 1794857439, "data": [{ "url": "http://.../v1/media/ima_xxx.webp", "size": "16:9", "kind": "image", "bytes": 98412 }] }`,
  },
  {
    ep: "POST /v1/videos",
    mode: "Text & Image-to-Video",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>, Content-Type: application/json
Body:
{
  "model": "muse-video",
  "prompt": "Golden maple leaves drifting in the wind",
  "duration": 5,
  "size": "16:9"
}
// Optional first-frame / refs: image, images, image_url, reference_image`,
    outputDoc: `POST -> { "id": "vid_xxx", "status": "queued", "progress": 10 }
GET /v1/videos/{id} -> { "id": "vid_xxx", "status": "completed", "progress": 100, "url": "http://.../v1/media/vid_xxx.mp4", "bytes": 4994013 }`,
  },
  {
    ep: "GET /v1/models",
    mode: "Full Model Aliases",
    inputDoc: `Headers: Authorization: Bearer <API_KEY>`,
    outputDoc: `{ "object": "list", "data": [{ "id": "muse-spark", "object": "model", "owned_by": "muse2apiv2" }, ...] }`,
  },
];

export function ApiKeysPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [openEp, setOpenEp] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["apikey"],
    queryFn: () => apiFetch<{ raw_key: string; created_at: number; rotated_at: number }>("/admin/apikey"),
  });

  const rotateMut = useMutation({
    mutationFn: () => apiFetch<{ raw_key: string }>("/admin/apikey/rotate", { method: "POST" }),
    onSuccess: () => {
      toast.success("API key rotated. Previous key is now invalid.");
      qc.invalidateQueries({ queryKey: ["apikey"] });
    },
    onError: (err: Error) => toast.error(`Rotate failed: ${err.message}`),
  });

  const rawKey = data?.raw_key || "";
  const baseUrl = `${window.location.origin}/v1`;

  const handleCopy = () => {
    if (!rawKey) return;
    navigator.clipboard.writeText(rawKey);
    setCopied(true);
    toast.info("API key copied to clipboard.");
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">API & Keys</h1>
        <p className="text-sm text-zinc-400">OpenAI-compatible /v1/* endpoint and single raw Bearer API key.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Client API Key</CardTitle>
          <CardDescription>
            Stored raw in SQLite for third-party apps. Rotating invalidates the previous key immediately.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-xs text-zinc-400">
            Base URL: <code className="rounded bg-zinc-950 px-2 py-0.5 text-zinc-200 border border-zinc-800">{baseUrl}</code>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              readOnly
              type={revealed ? "text" : "password"}
              value={rawKey}
              className="max-w-md font-mono text-xs"
            />
            <Button variant="outline" className="w-20" onClick={() => setRevealed((v) => !v)}>
              {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              {revealed ? "Hide" : "Show"}
            </Button>
            <Button variant="outline" className="w-24" onClick={handleCopy}>
              {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
              {copied ? "Copied" : "Copy"}
            </Button>
            <Button
              variant="danger"
              loading={rotateMut.isPending}
              onClick={() => {
                if (window.confirm("Rotate API key? Existing clients using the old key will get 401.")) {
                  rotateMut.mutate();
                }
              }}
            >
              <RefreshCw className="h-4 w-4" />
              Rotate Key
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Available /v1/* Endpoints</CardTitle>
          <CardDescription>Click any endpoint row to expand Input & Output schemas.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm">
            {ENDPOINTS.map((item) => {
              const isOpen = openEp === item.ep;
              return (
                <div key={item.ep} className="rounded-lg border border-zinc-800/80 bg-zinc-950/60 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setOpenEp(isOpen ? null : item.ep)}
                    className="flex w-full items-center justify-between px-3.5 py-2.5 text-left hover:bg-zinc-900/70 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2">
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 text-zinc-400" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-zinc-500" />
                      )}
                      <code className="font-mono text-xs text-zinc-200">{item.ep}</code>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-zinc-500">{item.mode}</span>
                      <Badge variant="success">Ready</Badge>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="border-t border-zinc-800/80 bg-zinc-950 p-3.5 space-y-3">
                      <div>
                        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">Input</div>
                        <pre className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900/70 p-2.5 text-[11px] text-zinc-300 font-mono whitespace-pre-wrap">
                          {item.inputDoc}
                        </pre>
                      </div>
                      <div>
                        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">Output</div>
                        <pre className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900/70 p-2.5 text-[11px] text-emerald-300/90 font-mono whitespace-pre-wrap">
                          {item.outputDoc}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
