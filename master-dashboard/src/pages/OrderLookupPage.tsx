import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { Panel, Button, TableSkeleton } from '../components/ui';

interface OrderDetails {
  order_id: string;
  status: string;
  total_amount_inr: string;
  created_at: string | null;
  delivered_at: string | null;
  items: Array<{ product_name: string; quantity: number; price_inr: string; category: string }>;
}

export const OrderLookupPage: React.FC = () => {
  const [params] = useSearchParams();
  const orderId = params.get('order_id') || '';
  const query = useQuery({
    queryKey: ['orderLookup', orderId],
    queryFn: async () => (await api.get(`/api/admin/v1/orders/${encodeURIComponent(orderId)}`)).data as OrderDetails,
    enabled: Boolean(orderId),
    retry: false,
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <div>
        <p className="micro-label">ORDER LOOKUP</p>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">Order Details</h1>
        <p className="text-sm text-[#B6D5D1] mt-1">Tenant-scoped, read-only order information.</p>
      </div>
      {!orderId ? (
        <Panel tier="data"><p className="text-sm text-[#B6D5D1]">Choose an order from global search to view its details.</p></Panel>
      ) : query.isLoading ? (
        <TableSkeleton rows={4} />
      ) : query.isError ? (
        <Panel tier="data" className="space-y-3"><p role="alert" className="text-sm text-[#FF8585]">Order details could not be loaded. Check access or retry.</p><Button size="sm" variant="secondary" onClick={() => query.refetch()}>Retry</Button></Panel>
      ) : query.data ? (
        <Panel tier="data" notchedLabel={query.data.order_id} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div><p className="text-xs uppercase text-[#84ABA6]">Status</p><p className="text-[#EAF6F4]">{query.data.status}</p></div>
            <div><p className="text-xs uppercase text-[#84ABA6]">Order total</p><p className="text-[#EAF6F4]">₹{query.data.total_amount_inr}</p></div>
            <div><p className="text-xs uppercase text-[#84ABA6]">Delivered</p><p className="text-[#EAF6F4]">{query.data.delivered_at ? new Date(query.data.delivered_at).toLocaleString() : 'Not recorded'}</p></div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-[rgba(63,210,192,0.2)]">
            <table className="w-full text-left text-sm"><thead><tr className="text-xs uppercase text-[#84ABA6]"><th className="p-3">Item</th><th className="p-3">Category</th><th className="p-3">Qty</th><th className="p-3">Unit price</th></tr></thead>
              <tbody>{query.data.items.map((item, index) => <tr key={`${item.product_name}-${index}`} className="border-t border-[rgba(63,210,192,0.12)] text-[#EAF6F4]"><td className="p-3">{item.product_name}</td><td className="p-3">{item.category}</td><td className="p-3">{item.quantity}</td><td className="p-3">₹{item.price_inr}</td></tr>)}</tbody>
            </table>
          </div>
        </Panel>
      ) : null}
    </div>
  );
};
