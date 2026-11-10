import Image from 'next/image';

export const metadata = { title: 'About' };

export default function About() {
  return (
    <main>
      <h1>About</h1>
      <p>next/image renders a plain img element.</p>
      <Image src="/pixel.png" alt="A single pixel" width={1} height={1} />
    </main>
  );
}
