const posts = {
  first: { title: 'First post', body: 'A page from a dynamic route, written at build time.' },
  second: { title: 'Second post', body: 'Another page from the same route.' },
};

export function generateStaticParams() {
  return Object.keys(posts).map((slug) => ({ slug }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }) {
  const { slug } = await params;
  return { title: posts[slug].title };
}

export default async function Post({ params }) {
  const { slug } = await params;
  const post = posts[slug];
  return (
    <main>
      <h1>{post.title}</h1>
      <p>{post.body}</p>
    </main>
  );
}
