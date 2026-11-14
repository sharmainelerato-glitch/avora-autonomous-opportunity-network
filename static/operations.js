/* AVORA operations: accessible, explicit consent; no simulated blockchain refunds. */
async function operationsView(){
 if(!state.user)return '<div class="page">Sign in to view your bookings, deliveries and updates.</div>';
 const [book,refunds,alerts,orders,aiStatus]=await Promise.all([
  api('/operations/bookings'),api('/operations/refund-requests'),api('/operations/notifications'),api('/marketplace/orders'),api('/operations/ai/status')
 ]);
 let orderDetail=[];
 for(const o of orders.slice(0,35)){
  try{const d=await api('/marketplace/near/orders/'+o.id);const tracking=await api('/operations/orders/'+o.id+'/delivery');d.avoraDelivery=tracking.delivery;orderDetail.push(d)}catch(err){}
 }
 const sellerBusinesses=state.providers.filter(p=>p.owner_id===state.user.id);
 const sellers=state.providers.filter(p=>p.owner_id!==null&&p.owner_id!==state.user.id);
 let services=[];
 for(const p of sellers.slice(0,30)){
  try{const all=await api('/marketplace/listings?provider_id='+p.id);services.push(...all.filter(l=>l.kind!=='Products'&&l.owner_id!==null))}catch(err){}
 }
 return shell(`<div class="page avora-ops">
 <span class="eyebrow">YOUR AVORA WORKSPACE</span><h1 class="page-title">Bookings, deliveries & support</h1>
 <p class="subtle">All confirmations are recorded in AVORA. Appointment booking and delivery updates are managed by providers. Refund approvals do not move funds; actual NEAR refunds must be separately signed and verified.</p>
 <div class="panel avora-ops-release-tools"><h2>Connected integrations</h2><div class="avora-ops-grid"><div><strong>AI provider: ${e(aiStatus.provider)}</strong><p>Model: ${e(aiStatus.model)} · ${aiStatus.configured?'API key configured':'API key missing'}</p><p class="subtle">Configuring a key is not proof of a successful model call. To verify, open your website opportunity and run Assemble opportunity; confirm the AI response says mode: llm.</p><a class="btn outline small" href="#/requests">Open opportunities</a></div><div><strong>Booking calendar export</strong><p class="subtle">Accepted appointments can be downloaded as .ics files for Google, Outlook, Apple and other calendar apps. This is an import, not automatic two-way calendar synchronization.</p></div></div></div>
 <div class="avora-ops-grid">
 <section class="panel"><h2>Request a service appointment</h2><p class="subtle">The provider must approve your requested time. No payment is collected by this form.</p>
 ${services.length?`<form data-operation="booking-create"><div class="field"><label>Registered provider and service</label><select name="listing_id" required>${services.map(l=>`<option value="${l.id}" data-pid="${l.provider_id}">${e(l.provider_name)} — ${e(l.title)}</option>`).join('')}</select></div><div class="field"><label>Requested date and time (your local timezone)</label><input name="start" type="datetime-local" required></div><div class="field"><label>Details for the provider</label><textarea name="note" minlength="5" maxlength="500" required placeholder="Describe what you need and where, without sharing sensitive information."></textarea></div><button class="btn">Send booking request</button></form>`:'<p class="notice">Register another service provider account to enable appointments. Fictional sample businesses cannot accept bookings.</p>'}</section>
 <section class="panel"><div class="head"><h2>Notifications</h2><span class="tag">${alerts.unread} unread</span></div>
 ${alerts.items.length?alerts.items.map(n=>`<article class="avora-ops-item"><div><b>${e(n.title)}</b><p>${e(n.body)}</p><small>${new Date(n.created*1000).toLocaleString()}</small></div>${!n.read_at?`<button class="btn small outline" data-ops-action="mark-read" data-id="${n.id}">Mark read</button>`:''}</article>`).join(''):'<p class="subtle">You are all caught up. New booking, delivery, and refund updates appear here.</p>'}
 </section></div>
 <section class="panel"><h2>Service appointments</h2>${book.length?book.map(b=>`<article class="avora-ops-item"><div><b>${e(b.listing_title)}</b> · ${e(b.provider_name)}<p>${new Date(b.requested_start).toLocaleString()} · <strong>${e(b.status)}</strong></p><p>${e(b.note)}</p></div><div class="form-actions">${(b.seller_id===state.user.id&&b.status==='REQUESTED')?`<button class="btn small" data-ops-action="booking-decision" data-id="${b.id}" data-status="ACCEPTED">Accept</button><button class="btn small outline" data-ops-action="booking-decision" data-id="${b.id}" data-status="DECLINED">Decline</button>`:''}${b.seller_id===state.user.id&&b.status==='ACCEPTED'?`<button class="btn small" data-ops-action="booking-decision" data-id="${b.id}" data-status="COMPLETED">Mark complete</button>`:''}${(b.buyer_id===state.user.id||b.seller_id===state.user.id)&&['REQUESTED','ACCEPTED'].includes(b.status)?`<button class="btn small outline" data-ops-action="booking-decision" data-id="${b.id}" data-status="CANCELLED">Cancel</button>`:''}${['ACCEPTED','COMPLETED'].includes(b.status)?`<button class="btn small outline" data-ops-action="calendar-export" data-id="${b.id}"><span aria-hidden="true">↓</span> Add to calendar (.ics)</button>`:''}</div></article>`).join(''):'<p class="subtle">No appointments yet.</p>'}</section>
 <section class="panel"><h2>NEAR orders & delivery</h2><p class="subtle">Seller-entered tracking is not independently verified by a courier.</p>
 ${orderDetail.length?orderDetail.map(o=>`<article class="avora-ops-item"><div><b>Order #${o.id} · ${e(o.provider_name)}</b><p>Payment: ${e(o.payment_status)} · <a href="#/market-order/${o.id}">View receipt & order</a></p>${o.avoraDelivery?`<p><strong>Seller delivery update: ${e(o.avoraDelivery.status)}</strong>${o.avoraDelivery.carrier?` · ${e(o.avoraDelivery.carrier)}`:''}${o.avoraDelivery.reference?` · Ref: ${e(o.avoraDelivery.reference)}`:''}</p>`:''}${o.avoraDelivery?.reference?`<button class="btn small outline" data-ops-action="carrier-lookup" data-id="${o.id}">Check live courier tracking (if configured)</button>`:''}</div>${o.payment_status==='VERIFIED'&&o.seller_user_id===state.user.id?`<form data-operation="delivery-update" data-order="${o.id}" class="avora-ops-form"><label>Delivery status<select name="status"><option>PREPARING</option><option>DISPATCHED</option><option>DELIVERED</option></select></label><input name="carrier" maxlength="100" placeholder="Carrier (optional)"><input name="reference" maxlength="120" placeholder="Tracking reference (optional)"><input name="note" maxlength="500" placeholder="Delivery update"><button class="btn small">Save tracking</button></form>`:''}${o.payment_status==='VERIFIED'&&o.buyer_id===state.user.id?`<form data-operation="refund-request" data-order="${o.id}" class="avora-ops-form"><input name="reason" required minlength="12" maxlength="1200" placeholder="Reason for refund request"><button class="btn small outline">Request refund review</button></form>`:''}<div data-delivery-id="${o.id}"></div></article>`).join(''):'<p class="subtle">No NEAR checkout orders yet.</p>'}</section>
 <section class="panel"><h2>Refund review requests</h2><p class="notice">A seller's approval is only a decision to arrange a refund. No NEAR funds are returned automatically, and there is no verified refund receipt without a separate on-chain transfer.</p>${refunds.length?refunds.map(r=>`<article class="avora-ops-item"><div><b>Order #${r.order_id} · ${e(r.status)}</b><p>${e(r.reason)}</p>${r.response_note?`<p>Seller response: ${e(r.response_note)}</p>`:''}</div>${r.seller_id===state.user.id&&r.status==='REQUESTED'?`<div class="form-actions"><button class="btn small" data-ops-action="refund-decision" data-id="${r.id}" data-status="APPROVED_MANUAL">Approve review</button><button class="btn small outline" data-ops-action="refund-decision" data-id="${r.id}" data-status="DECLINED">Decline</button></div>`:''}${r.status==='APPROVED_MANUAL'?`<div class="avora-ops-refund"><button class="btn small outline" data-ops-action="refund-instructions" data-id="${r.id}">View exact NEAR refund instructions</button><form data-operation="refund-proof" data-id="${r.id}" class="avora-ops-form"><label>Refund transaction hash<input name="tx_hash" minlength="40" maxlength="48" required placeholder="Real NEAR testnet hash" /></label><label>Sending provider account<input name="sender_account_id" required placeholder="business.testnet" /></label><button class="btn small">Verify repayment on-chain</button></form></div>`:''}${r.status==='REFUNDED_VERIFIED'?`<p class="notice">Repayment independently verified on NEAR testnet. The original transfer was not reversed. ${r.verified_refund_hash?`<a target="_blank" rel="noopener noreferrer" href="https://testnet.nearblocks.io/txns/${e(r.verified_refund_hash)}">View repayment proof ↗</a>`:''}</p>`:''}</article>`).join(''):'<p class="subtle">No refund requests.</p>'}</section>
 <section class="panel"><h2>Business evidence review</h2><p class="subtle">Submit a public registration/business evidence link for operator review. AVORA does not independently verify identity or government documents. Do not upload IDs, passwords, or private documents.</p>${sellerBusinesses.map(p=>`<form data-operation="verification-submit" data-id="${p.id}" class="avora-ops-form"><strong>${e(p.name)}</strong><input name="registry_reference" placeholder="Public business registration reference" required maxlength="100"><input name="public_evidence_url" type="url" placeholder="https://public-register.example/business" required><textarea name="note" maxlength="500" placeholder="Optional context for reviewer"></textarea><button class="btn small outline">Submit public evidence for review</button><div class="meta" data-verification-id="${p.id}">Review is not government identity verification</div></form>`).join('')||'<p class="subtle">Create a provider profile to submit public business evidence.</p>'}</section>
 </div>`);
}
document.addEventListener('submit',async event=>{
 const form=event.target.closest('form[data-operation]');if(!form)return;
 event.preventDefault();event.stopImmediatePropagation();
 const data=new FormData(form),button=form.querySelector('button[type=submit],button:not([type])');if(button)button.disabled=true;
 try{
  if(form.dataset.operation==='booking-create'){
   const opt=form.querySelector('select[name=listing_id] option:checked');
   const value=new Date(String(data.get('start')));
   if(!Number.isFinite(value.getTime()))throw Error('Choose a valid future date and time');
   await api('/operations/bookings',{method:'POST',body:JSON.stringify({provider_id:Number(opt.dataset.pid),listing_id:Number(opt.value),requested_start:value.toISOString(),note:String(data.get('note'))})});
   toast('Booking request sent. No payment was collected.');
  }
  if(form.dataset.operation==='delivery-update'){
   await api('/operations/orders/'+form.dataset.order+'/delivery',{method:'PUT',body:JSON.stringify({status:String(data.get('status')),carrier:String(data.get('carrier')||''),reference:String(data.get('reference')||''),note:String(data.get('note')||'')})});toast('Seller delivery update saved');
  }
  if(form.dataset.operation==='verification-submit'){
   const res=await api('/operations/verification/'+form.dataset.id,{method:'POST',body:JSON.stringify({registry_reference:String(data.get('registry_reference')),public_evidence_url:String(data.get('public_evidence_url')),note:String(data.get('note')||'')})});
   toast('Evidence submitted for manual review. Identity is NOT verified.');
  }
  if(form.dataset.operation==='refund-proof'){
   if(!await nearDialog({title:'Verify a separately signed refund',message:'This does not send NEAR. Confirm the seller already signed a separate exact testnet repayment. AVORA will inspect the blockchain proof.',confirmText:'Verify transaction'}))return;
   const out=await api('/operations/refund-requests/'+form.dataset.id+'/verify',{method:'POST',body:JSON.stringify({tx_hash:String(data.get('tx_hash')).trim(),signer_account_id:String(data.get('sender_account_id')).trim()})});
   toast('Refund independently verified on NEAR testnet.');
  }
  if(form.dataset.operation==='refund-request'){
   if(!await nearDialog({title:'Submit a refund review request',message:'This asks the seller to review your request. It will not reverse the NEAR payment.',confirmText:'Request review'}))return;
   await api('/operations/orders/'+form.dataset.order+'/refund-request',{method:'POST',body:JSON.stringify({reason:String(data.get('reason'))})});toast('Refund request submitted; no funds moved.');
  }
  await render();
 }catch(err){toast('Could not save: '+err.message)}finally{if(button)button.disabled=false}
},true);
document.addEventListener('click',async event=>{
 const button=event.target.closest('button[data-ops-action]');if(!button)return;
 try{
  const action=button.dataset.opsAction;
  if(action==='calendar-export'){
    const response=await fetch('/api/operations/bookings/'+button.dataset.id+'/calendar.ics',{headers:{Authorization:'Bearer '+state.token}});
    if(!response.ok){let detail=await response.json().catch(()=>({}));throw Error(detail.detail||'Calendar export failed')}
    const blob=await response.blob(),href=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=href;link.download='avora-booking-'+button.dataset.id+'.ics';document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(href),5000);toast('Calendar file downloaded. Import it into your calendar app.');return;
  }
  if(action==='carrier-lookup'){
    const live=await api('/operations/orders/'+button.dataset.id+'/carrier-lookup');
    await nearDialog({title:'Courier tracking — '+live.source,message:'Status: '+live.status+'; carrier: '+live.carrier+'; reference: '+live.tracking_code+'; mode: '+live.mode+'; latest carrier update: '+(live.last_carrier_event?.message||'No event available')+'. '+live.notice,confirmText:'Close'});return;
  }
  if(action==='refund-instructions'){
    const i=await api('/operations/refund-requests/'+button.dataset.id+'/instructions');
    await nearDialog({title:'Approved full testnet refund',message:'The provider must separately sign a NEW transfer of '+i.amount_near+' testnet NEAR FROM '+i.from_account+' TO '+i.to_account+'. No funds move inside AVORA. Once complete, enter the real transaction hash in the refund form.',confirmText:'Understood',cancelText:'Close'});return;
  }
  if(action==='mark-read')await api('/operations/notifications/'+button.dataset.id+'/read',{method:'POST'});
  else if(action==='booking-decision'){
    if(!await nearDialog({title:'Confirm booking '+button.dataset.status.toLowerCase(),message:'This updates the appointment status inside AVORA. It does not transfer funds.',confirmText:'Confirm'}))return;
    await api('/operations/bookings/'+button.dataset.id+'/decision',{method:'POST',body:JSON.stringify({status:button.dataset.status})});
  }else if(action==='refund-decision'){
    if(!await nearDialog({title:'Respond to refund request',message:'An approval records an agreement to arrange a separate refund. AVORA does not send NEAR or mark a refund paid.',confirmText:'Record decision'}))return;
    await api('/operations/refund-requests/'+button.dataset.id+'/decision',{method:'POST',body:JSON.stringify({decision:button.dataset.status,note:''})});
  }
  await render();
 }catch(err){toast('Could not complete: '+err.message)}
},true);

// Lightweight notification polling, not push/websocket delivery.
let avoraLastUnread=null;
window.setInterval(async()=>{
 if(!state.user||!state.token)return;
 try{const data=await api('/operations/notifications');
 if(avoraLastUnread!==null&&data.unread>avoraLastUnread)toast('New AVORA notification — open Bookings & updates.');
 avoraLastUnread=data.unread;
 }catch(_err){ /* Skip while offline or signed out. */ }
},30000);
