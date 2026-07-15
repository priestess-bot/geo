export type ProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  code?: string;
  correlation_id?: string;
};

export type JobAccepted = {
  job_id: string;
  status: "queued";
  status_url: string;
};
