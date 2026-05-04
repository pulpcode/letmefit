import { request, uploadFile } from "../utils/request";
import type { UploadFile } from "../types/api";

type UploadRecordInput = {
  client_local_ref: string;
  mime_type: string;
  size_bytes?: number;
  source: "camera" | "album" | "microphone" | "upload";
};

export function createClientLocalUpload(input: UploadRecordInput) {
  return request<{ file: UploadFile; upload_url: string | null; upload_headers: Record<string, string> }>({
    path: "/uploads",
    method: "POST",
    data: {
      storage_provider: "client_local",
      client_local_ref: input.client_local_ref,
      mime_type: input.mime_type,
      size_bytes: input.size_bytes,
      source: input.source,
      retention_policy: "transient"
    }
  });
}

type LocalFileUploadInput = {
  filePath: string;
  mime_type: string;
  source: "microphone";
};

export function uploadLocalFile(input: LocalFileUploadInput) {
  return uploadFile<{ file: UploadFile; upload_url: string | null; upload_headers: Record<string, string> }>({
    path: "/uploads/local-file",
    filePath: input.filePath,
    name: "file",
    formData: {
      mime_type: input.mime_type,
      source: input.source,
      retention_policy: "transient"
    }
  });
}
