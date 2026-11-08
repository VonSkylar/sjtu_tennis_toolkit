// Shared by the isolated page agent, extension worker and rule tests.
globalThis.SJTU_ROUTE = Object.freeze({
  matches(value,venueId) {
    if(!venueId) return false;
    try {
      const url=new URL(value);
      if(url.origin!==globalThis.SJTU_BOOKING_RULES.schoolOrigin||!/^\/pc\/?$/.test(url.pathname)) return false;
      const route=url.hash.match(/^#\/apointmentDetails\/[^/]+\/([^/?#]+)(?:\/|$)/);
      return Boolean(route&&decodeURIComponent(route[1])===venueId);
    }catch {return false;}
  }
});
