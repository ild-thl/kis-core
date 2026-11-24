/** A tool page started, cancelled or deleted a job. */
export const JOBS_CHANGED_EVENT = "askf-jobs-changed";
/** The job list saw a status change, pages that show jobs load again. */
export const JOBS_STATUS_CHANGED_EVENT = "askf-jobs-status-changed";

export function notifyJobsChanged(): void {
  window.dispatchEvent(new CustomEvent(JOBS_CHANGED_EVENT));
}
