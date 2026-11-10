import Link from 'next/link';
import './globals.css';

export const metadata = {
  title: 'Fixture site',
  description: 'A static site whose pages need no JavaScript.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB">
      <head>
        {/* The site's own script. data-keep tells next-export-strip-js to leave it. */}
        <script data-keep src="/js/site.js" defer></script>
      </head>
      <body>
        <nav>
          <Link href="/">Home</Link>
          <Link href="/about">About</Link>
          <Link href="/posts/first">First post</Link>
          <Link href="/posts/second">Second post</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
