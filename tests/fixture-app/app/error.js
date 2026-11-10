'use client';

// An error boundary must be a client component. React only renders it in the
// browser, after an error there, so next-export-strip-js ignores it.
export default function Error({ reset }) {
  return (
    <div>
      <p>Something went wrong.</p>
      <button type="button" onClick={() => reset()}>Try again</button>
    </div>
  );
}
