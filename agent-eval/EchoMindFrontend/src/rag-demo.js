// Explicit Demo policies and human-authored relevance labels. No scores/results.
export const demoDocuments = [
  ['refund','退款到账','退款审核通过后，原付款方式退回，到账时间五至七个工作日。申请需要订单号，不能直接宣称退款完成。'],
  ['opened','拆封商品退货','已拆封商品七天无理由退货条件：保持完整包装，不影响二次销售；定制商品不适用。先核验订单号和商品状态。'],
  ['delivery','物流超时','配送物流超时：查询运单最新揽收和运输节点，联系承运人核验延迟原因，不能保证未经确认的送达时间。'],
  ['invoice','电子发票','电子发票申请：订单完成后在订单页面填写抬头、税号和电子邮箱，可下载电子发票用于报销。'],
  ['password','账户密码重置','忘记密码无法登录时，通过已绑定手机获取验证码进行账户重置；客服不索要明文密码。'],
  ['points','会员积分','会员积分：每消费一元获得一个积分，一百积分可兑换一元优惠；以账户实际积分余额为准。'],
  ['address','修改收货地址','修改收货地址：揽收前可在订单页面提交新地址。揽收后联系承运人核验是否可拦截，不能直接承诺修改成功。'],
  ['warranty','保修与维修','保修质量故障：保修期内的非人为质量故障，提供订单号、故障描述和照片，售后核验后安排维修。'],
].map(([document_id,title,text]) => ({ document_id,title,text,metadata:{purpose:'DEMO_POLICY_NOT_BUSINESS_COMMITMENT'} }))
export const demoCases = [
  ['opened','拆了还能退吗？','保持完整包装、不影响二次销售，需要核验订单号和商品状态。'],
  ['refund','钱什么时候回到卡里？','审核通过后五至七个工作日原路退回。'],
  ['delivery','包裹咋还没动？','查询运单节点，核验物流延迟。'],
  ['invoice','报销的凭证怎么弄？','订单完成后填写发票抬头、税号、邮箱。'],
  ['password','进不去账户了怎么办？','通过绑定手机验证码重置，不索要密码。'],
  ['points','花的钱有奖励吗？','每一元消费一个积分，一百积分兑换一元。'],
  ['address','送错地方能改吗？','揽收前修改，揽收后核验可否拦截。'],
  ['warranty','买的坏了找谁？','提供订单和故障证据，经核验安排保修。'],
].map(([id,query,expected_answer],i) => ({case_id:`rag_${i+1}`,query,relevant_document_ids:[id],expected_answer,source:'demo'}))
