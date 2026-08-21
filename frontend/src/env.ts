import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://localhost:8000/api"),
  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("PDFTalk"),
  NEXT_PUBLIC_MAX_UPLOAD_MB: z.coerce.number().positive().default(20),
});

export const env = envSchema.parse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_MAX_UPLOAD_MB:
    process.env.NEXT_PUBLIC_MAX_UPLOAD_MB,
});
