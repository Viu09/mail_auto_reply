export type AccountSummary = {
  account_id: string;
  label: string;
  pending: number;
  sent: number;
  rejected: number;
  total: number;
};

export type Attachment = {
  id: number;
  file_name: string;
  mime_type: string | null;
};

export type Email = {
  id: number;
  account_id: string;
  gmail_id: string;
  sender: string;
  reply_to: string;
  subject: string;
  snippet: string;
  body_text: string;
  attachment_names: string[];
  attachment_analysis: string;
  summary: string;
  detailed_summary: string;
  category: string;
  tags: string[];
  priority: "low" | "medium" | "high";
  suggested_reply: string;
  should_reply: boolean;
  required_documents: string[];
  provided_documents: string[];
  target_language: string;
  approval_status: "pending" | "sent" | "rejected";
  sent_message_id: string | null;
  marked_read: boolean;
  received_at: string | null;
  created_at: string;
  updated_at: string;
  attachments?: Attachment[];
};

export type CategoryCount = {
  name: string;
  count: number;
};

export type Document = {
  id: number;
  account_id: string;
  email_id: number | null;
  gmail_id: string;
  file_name: string;
  mime_type: string | null;
  size_bytes: number;
  category: string;
  summary: string;
  sender: string;
  subject: string;
  received_at: string | null;
  created_at: string;
};

export type Rule = {
  id: number;
  account_id: string | null;
  name: string;
  category: string | null;
  max_priority: string | null;
  action: "auto_send" | "auto_reject" | "flag";
  enabled: boolean;
  created_at: string;
};
