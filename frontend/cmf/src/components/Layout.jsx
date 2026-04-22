import React, { useState } from "react";
import { Layout } from "antd";
import { useLocation } from "react-router-dom";
import Sidebar from "./ui/sidebar";
import Navbar from "./ui/Navbar";
import Footer from "./ui/Footer";

const { Content } = Layout;

const AppLayout = ({ children }) => {
  const location = useLocation();
  const isLoginPage = location.pathname === '/login';
  const isInspectorPage =
    location.pathname === '/admin/qms-inspector' ||
    location.pathname === '/supervisor/qms-inspector' ||
    location.pathname === '/operator/qms-inspector';
  const isOperatorInspectionQueue = location.pathname.includes('/operator/inspection-results');
  const [collapsed, setCollapsed] = useState(false);

  if (isLoginPage || isInspectorPage) {
    return <>{children}</>;
  }

  return (
    <Layout hasSider style={{ height: '100vh', overflow: 'hidden' }}>
      <Sidebar collapsed={collapsed} onCollapse={setCollapsed} />
      <Layout 
        style={{ 
          marginLeft: collapsed ? 80 : 224,
          height: '100vh',
          overflow: 'hidden',
          transition: 'all 0.2s'
        }}
        className="responsive-layout"
      >
        <style>{`
          @media (max-width: 768px) {
            .responsive-layout {
              margin-left: 0 !important;
            }
          }
        `}</style>
        <Navbar collapsed={collapsed} />
        <Content 
          style={{ 
            margin: isOperatorInspectionQueue
              ? 'clamp(50px, 10vw, 60px) 8px clamp(24px, 4vw, 36px)'
              : 'clamp(50px, 10vw, 60px) clamp(12px, 3vw, 24px) clamp(30px, 5vw, 40px)',
            overflowY: 'auto',
            overflowX: 'hidden',
            backgroundColor: 'transparent',
            padding: 0,
            width: '100%',
            maxWidth: '100%',
            boxSizing: 'border-box',
          }}
        >
          {children}
        </Content>
        <Footer collapsed={collapsed} />
      </Layout>
    </Layout>
  );
};

export default AppLayout;
