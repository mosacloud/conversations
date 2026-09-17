import { Suspense } from 'react';

import { Loader } from '@/components';
import { Chat } from '@/features/chat/components/Chat';

const Page = () => {
  return (
    <Suspense fallback={<Loader />}>
      <Chat initialConversationId={undefined} />
    </Suspense>
  );
};

export default Page;
